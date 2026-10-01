"""Forward paper test: does lineup information beat the unadjusted model and the market?

Run it roughly hourly (cron / scheduled session). Each run, for every open club market whose
kickoff is within the lineup window (default 15-90 min away) and not already logged:
fetch confirmed lineups (1 API-Football request per game), then price the market with three
models off the *same* order book and log all three:
  base  - the unadjusted MLE Dixon-Coles model
  stat  - base with a missing-regular-starter adjustment (lineup/adjust.py, unvalidated priors)
  llm   - base with Claude's lineup adjustment (needs ANTHROPIC_API_KEY / KALSHI_ANTHROPIC_KEY)

    python scripts/shadow_lineup.py                 # log + settle + scorecard
    python scripts/shadow_lineup.py --settle-only   # just settle and print the scorecard
    python scripts/shadow_lineup.py --no-llm        # skip the LLM variant

Writes to $SIGNALS_DB (default data/football.sqlite). Needs data/clubs.sqlite
(scripts/build_club_db.py) and API_FOOTBALL_KEY. Read-only against Kalshi; places no orders.
"""
import argparse
import os
import sys
from datetime import datetime, timezone

import httpx

from kalshi_edge.config import CLUB_LEAGUES, KALSHI_BASE_URL, anthropic_api_key, load_env
from kalshi_edge.data.cache import connect
from kalshi_edge.data.club_results import FIXTURES_URL, load_fixtures_csv
from kalshi_edge.edge.club_shadow import build_club_signals
from kalshi_edge.edge.engine import EdgeEngine
from kalshi_edge.edge.policy import DEFAULT_POLICY
from kalshi_edge.edge.settle import fetch_result
from kalshi_edge.enrich.apifootball import ApiFootball
from kalshi_edge.kalshi.client import KalshiClient
from kalshi_edge.kalshi.http import KalshiHTTP
from kalshi_edge.lineup import store
from kalshi_edge.lineup.adjust import goal_multipliers
from kalshi_edge.lineup.history import ensure_history, missing_regulars, record_lineup
from kalshi_edge.lineup.lineups import (fetch_match_lineups, find_fixture, fixtures_for_day, iso)
from kalshi_edge.lineup.llm import LineupLLM
from kalshi_edge.model.mle_model import MLEGoalModel
from kalshi_edge.model.poisson import score_matrix
from kalshi_edge.pricer.pricer import Pricer

CLUB_DB = "data/clubs.sqlite"


def scaled_pricer(model, home, away, h_mult, a_mult) -> Pricer:
    lam, mu = model.expected_goals(home, away, neutral=False)
    return Pricer(score_matrix(lam * h_mult, mu * a_mult, model.fit.rho, model.max_goals), home, away)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--min-lead", type=int, default=15, help="skip kickoffs sooner than this (minutes)")
    p.add_argument("--max-lead", type=int, default=90, help="skip kickoffs later than this (minutes)")
    p.add_argument("--api-budget", type=int, default=40, help="max API-Football requests this run")
    p.add_argument("--no-llm", action="store_true")
    p.add_argument("--settle-only", action="store_true")
    args = p.parse_args(argv)
    load_env()

    sconn = connect(os.environ.get("SIGNALS_DB") or "data/football.sqlite")
    store.ensure_store(sconn)
    ensure_history(sconn)
    client = KalshiClient(http=KalshiHTTP(base_url=KALSHI_BASE_URL, timeout=20.0, max_retries=4))

    if not args.settle_only:
        rc = log_run(args, sconn, client)
        if rc:
            return rc
    print(store.settle(sconn, lambda t: fetch_result(client, t)))
    print(store.render_scorecard(store.scorecard(sconn)))
    return 0


def log_run(args, sconn, client) -> int:
    now = datetime.now(timezone.utc)
    if not os.environ.get("API_FOOTBALL_KEY"):
        print("API_FOOTBALL_KEY not set.")
        return 1
    if not os.path.exists(CLUB_DB):
        print(f"{CLUB_DB} missing - run scripts/build_club_db.py first.")
        return 1
    model = MLEGoalModel.from_db(connect(CLUB_DB), ref_date=now.date().isoformat(),
                                 since="2019-07-01", min_games=10)
    fix = connect(":memory:")
    resp = httpx.get(FIXTURES_URL, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    load_fixtures_csv(fix, resp.content.decode("utf-8-sig", "replace"))

    api = ApiFootball(conn=sconn, max_calls=args.api_budget)
    llm = None if args.no_llm or not anthropic_api_key() else LineupLLM()
    if llm is None and not args.no_llm:
        print("No Anthropic key found - skipping the llm variant.")
    done = store.logged_events(sconn)
    day_fixtures: dict = {}
    stats = {"api_fixture_unmatched": 0, "llm_failed": 0, "api_error": 0}

    def variants_for(home, away, kickoff, event):
        if event in done:
            return None
        try:
            day = kickoff.date()
            if day not in day_fixtures:
                day_fixtures[day] = fixtures_for_day(api, day)
            fx = find_fixture(day_fixtures[day], home, away, kickoff)
            if fx is None:
                stats["api_fixture_unmatched"] += 1
                return None
            lineups = fetch_match_lineups(api, fx)
        except (RuntimeError, httpx.HTTPError) as e:
            stats["api_error"] += 1
            print(f"  API-Football: {e}")
            return None
        if lineups is None:
            return None
        h_lu, a_lu = lineups
        before = kickoff.isoformat()
        h_miss = missing_regulars(sconn, home, h_lu, before)
        a_miss = missing_regulars(sconn, away, a_lu, before)
        record_lineup(sconn, home, fx["fixture"]["id"], before, h_lu)
        record_lineup(sconn, away, fx["fixture"]["id"], before, a_lu)
        miss_info = {"home_missing": [m["name"] for m in h_miss], "away_missing": [m["name"] for m in a_miss]}
        hm, am = goal_multipliers(h_miss, a_miss)
        out = {"stat": (scaled_pricer(model, home, away, hm, am),
                        {**miss_info, "home_mult": hm, "away_mult": am})}
        if llm is not None:
            lam, mu = model.expected_goals(home, away, neutral=False)
            res = llm.adjust({"league": "club football", "home": home, "away": away,
                              "kickoff": kickoff.isoformat(), "xg_home": lam, "xg_away": mu,
                              "home_lineup": h_lu, "away_lineup": a_lu,
                              "home_missing": h_miss, "away_missing": a_miss})
            if res is None:
                stats["llm_failed"] += 1
            else:
                lh, la, why = res
                out["llm"] = (scaled_pricer(model, home, away, lh, la),
                              {**miss_info, "home_mult": lh, "away_mult": la, "reason": why})
        done.add(event)
        return out

    signals, bstats = build_club_signals(
        client, model, fix, EdgeEngine.from_policy(DEFAULT_POLICY), now=now,
        intended_size=DEFAULT_POLICY.intended_size, min_lead_minutes=args.min_lead,
        max_lead_minutes=args.max_lead, variants_for=variants_for)
    for sig in signals:
        if sig.market_implied > 0:
            store.log_variant_signal(sconn, sig)
    print(f"Logged {sum(1 for s in signals if s.market_implied > 0)} rows. "
          f"API requests used: {api.calls}. Stats: {bstats} {stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
