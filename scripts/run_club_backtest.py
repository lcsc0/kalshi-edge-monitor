"""Backtest the goal model against Kalshi club-soccer markets (EPL, La Liga, ...).

Unlike the World Cup (one tournament per 4 years) club leagues give thousands of
settled markets per season. Pipeline per settled market:
  Kalshi event -> fixture in data/clubs.sqlite (fuzzy, date-constrained)
  -> real kickoff time (football-data) -> candle price `--lead-hours` before it
  -> MLE model fit on matches strictly before the match week -> model_fair.

Usage:
    python scripts/build_club_db.py
    python scripts/run_club_backtest.py [--leagues EPL,LALIGA] [--kinds GAME,TOTAL,BTTS]
        [--lead-hours 1] [--max-per-series 0] [--workers 8]
"""
import argparse
import re
import sys
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from kalshi_edge.backtest.edge_metrics import KellyConfig
from kalshi_edge.backtest.harness import render_report, run_backtest
from kalshi_edge.backtest.replay import (
    HistoricalMarket, LookaheadError, parse_contract, replay_market)
from kalshi_edge.config import CLUB_LEAGUES, CLUB_MARKET_KINDS, KALSHI_BASE_URL
from kalshi_edge.data.cache import connect
from kalshi_edge.edge.policy import DEFAULT_POLICY
from kalshi_edge.kalshi.client import KalshiClient
from kalshi_edge.kalshi.club_match import (
    event_date, event_suffix, resolve_event, title_teams)
from kalshi_edge.kalshi.http import KalshiHTTP
from kalshi_edge.model.mle_model import MLEGoalModel


def _client() -> KalshiClient:
    return KalshiClient(http=KalshiHTTP(base_url=KALSHI_BASE_URL, timeout=20.0, max_retries=5))


def _prior_monday(day) -> str:
    """Most recent Monday strictly before ``day`` — fits are shared per week."""
    d = day - timedelta(days=1)
    return (d - timedelta(days=d.weekday())).isoformat()


def _ckey(job, args) -> str:
    return f"{job[0]['ticker']}|{args.lead_hours}"


def _load_cache(path):
    import json, os
    if path and os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return {}


def _save_cache(path, cache):
    import json, os
    if path:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            json.dump(cache, f)


def collect_markets(leagues, kinds, max_per_series):
    """-> {league: {kind: [settled market dicts]}} (archive covers older markets)."""
    out = {}
    for lg in leagues:
        out[lg] = {}
        for kind in kinds:
            series = f"KX{lg}{kind}"
            rows = []
            try:
                for m in _client().iter_historical_markets(series_ticker=series):
                    if (m.get("result") or "").lower() in ("yes", "no"):
                        rows.append(m)
                    if max_per_series and len(rows) >= max_per_series:
                        break
            except Exception as exc:  # a missing series just means no data
                print(f"  {series}: {type(exc).__name__}: {exc}")
            out[lg][kind] = rows
            print(f"  {series}: {len(rows)} settled markets")
    return out


def event_matches(conn, league, by_kind, stats, unresolved):
    """event suffix -> (db_row, home_kalshi, away_kalshi), from the league's GAME markets."""
    tournament = CLUB_LEAGUES[league]
    resolved, seen = {}, set()
    for m in by_kind.get("GAME", []):
        suffix = event_suffix(m.get("event_ticker") or m["ticker"].rsplit("-", 1)[0])
        if suffix in seen:
            continue
        seen.add(suffix)
        teams, day = title_teams(m.get("title", "")), event_date(suffix)
        hit = resolve_event(conn, tournament, day, *teams) if teams and day else None
        if hit:
            resolved[suffix] = hit
        else:
            stats["event_unresolved"] += 1
            unresolved[(league, teams)] += 1
    return resolved


def build_signals(conn, markets, args):
    stats = Counter()
    unresolved: Counter = Counter()
    jobs = []  # (market dict, league, kind, HistoricalMarket-in-progress)
    for lg, by_kind in markets.items():
        resolved = event_matches(conn, lg, by_kind, stats, unresolved)
        for kind, rows in by_kind.items():
            for m in rows:
                stats["markets"] += 1
                suffix = event_suffix(m.get("event_ticker") or m["ticker"].rsplit("-", 1)[0])
                hit = resolved.get(suffix)
                if hit is None:
                    stats["unmapped_event"] += 1
                    continue
                row, home_k, away_k = hit
                ko = conn.execute(
                    "SELECT kickoff_utc FROM kickoffs WHERE date=? AND home_team=? AND away_team=?",
                    (row["date"], row["home_team"], row["away_team"])).fetchone()
                if ko is None:
                    stats["no_kickoff"] += 1
                    continue
                series = m["ticker"].split("-")[0]
                sub = m.get("yes_sub_title") or m.get("subtitle") or ""
                contract = parse_contract(series, sub, home_k, away_k)
                if contract is None:
                    stats["unmapped_contract"] += 1
                    continue
                kickoff = datetime.fromtimestamp(ko[0], tz=timezone.utc)
                jobs.append((m, kind, HistoricalMarket(
                    ticker=m["ticker"], series=series, home=row["home_team"],
                    away=row["away_team"], kickoff=kickoff, contract=contract,
                    settled_yes=m["result"].lower() == "yes", neutral=False)))

    print(f"Fetching candles for {len(jobs)} markets ({args.workers} workers)...")

    def fetch(job):
        m, _, hm = job
        pre = int((hm.kickoff - timedelta(hours=args.lead_hours)).timestamp())
        try:
            return _client().get_historical_candlesticks(
                m["ticker"], start_ts=int((hm.kickoff - timedelta(days=3)).timestamp()),
                end_ts=pre, period_interval=60)
        except Exception:
            return None

    # Candles are slow to fetch (one call per market) and immutable once settled:
    # cache them on disk so reruns and crashes don't repeat thousands of calls.
    cache = _load_cache(args.candle_cache)
    todo = [j for j in jobs if _ckey(j, args) not in cache]
    print(f"  {len(jobs) - len(todo)} cached, {len(todo)} to fetch")
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for job, res in zip(todo, pool.map(fetch, todo)):
            if res is not None:
                cache[_ckey(job, args)] = res
    _save_cache(args.candle_cache, cache)
    candles_all = [cache.get(_ckey(j, args)) for j in jobs]

    fits: dict = {}
    signals, kinds_of = [], []
    for (m, kind, hm), candles in zip(jobs, candles_all):
        if candles is None:
            stats["candle_error"] += 1
            continue
        ref = _prior_monday(hm.kickoff.date())
        if ref not in fits:
            fits[ref] = MLEGoalModel.from_db(conn, ref_date=ref, since=args.since, min_games=10)
        model = fits[ref]
        if hm.home not in model.fit.attack or hm.away not in model.fit.attack:
            stats["unknown_team"] += 1
            continue
        pre = int((hm.kickoff - timedelta(hours=args.lead_hours)).timestamp())
        try:
            sig = replay_market(conn, hm, ref_date=ref, pre_close_ts=pre, candles=candles,
                                since=args.since, model=model)
        except LookaheadError:
            stats["lookahead_skip"] += 1
            continue
        except (ValueError, KeyError, TypeError):
            stats["pricer_error"] += 1
            continue
        if sig is None:
            stats["no_price"] += 1
            continue
        signals.append(sig)
        kinds_of.append(f"{hm.series.split('-')[0]}")
        stats["signals"] += 1
    return signals, kinds_of, stats, unresolved


def breakdown(signals, labels):
    """Model vs market Brier per series: the market is the benchmark to beat."""
    g = defaultdict(list)
    for s, lab in zip(signals, labels):
        g[lab].append(s)
    print(f"\n{'series':22} {'n':>5} {'model':>6} {'mkt':>6} {'real':>6} {'Brier_model':>11} {'Brier_mkt':>10}")
    tot_m = tot_k = 0.0
    for lab, v in sorted(g.items(), key=lambda kv: -len(kv[1])):
        n = len(v)
        bm = sum((x.model_fair - x.realized_outcome) ** 2 for x in v) / n
        bk = sum((x.market_price - x.realized_outcome) ** 2 for x in v) / n
        tot_m += bm * n
        tot_k += bk * n
        print(f"{lab:22} {n:5d} {sum(x.model_fair for x in v)/n:6.3f} "
              f"{sum(x.market_price for x in v)/n:6.3f} {sum(x.realized_outcome for x in v)/n:6.3f} "
              f"{bm:11.4f} {bk:10.4f}")
    n = len(signals)
    print(f"{'ALL':22} {n:5d} {'':6} {'':6} {'':6} {tot_m/n:11.4f} {tot_k/n:10.4f}")


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Backtest the goal model on Kalshi club-soccer markets.")
    p.add_argument("--db", default="data/clubs.sqlite")
    p.add_argument("--leagues", default=",".join(CLUB_LEAGUES))
    p.add_argument("--kinds", default="GAME,TOTAL,BTTS", help=f"subset of {CLUB_MARKET_KINDS}")
    p.add_argument("--lead-hours", type=float, default=1.0)
    p.add_argument("--since", default="2019-07-01")
    p.add_argument("--max-per-series", type=int, default=0, help="0 = all")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--dump-signals", default="", help="write every signal to this CSV")
    p.add_argument("--candle-cache", default="data/club_candles.json",
                   help="on-disk candle cache ('' to disable)")
    args = p.parse_args(argv)

    import os
    if not os.path.exists(args.db):
        print(f"{args.db!r} not found — run scripts/build_club_db.py first.")
        return 1
    conn = connect(args.db)
    leagues = [x for x in args.leagues.split(",") if x]
    kinds = [x for x in args.kinds.split(",") if x]
    print("Collecting settled Kalshi markets...")
    markets = collect_markets(leagues, kinds, args.max_per_series)
    signals, labels, stats, unresolved = build_signals(conn, markets, args)

    print("\n" + ", ".join(f"{k}={v}" for k, v in sorted(stats.items())))
    if unresolved:
        print("Top unresolved Kalshi pairings (extend club_match._ALIASES):")
        for (lg, teams), c in unresolved.most_common(15):
            print(f"  {lg}: {teams} x{c}")
    if not signals:
        print("No usable signals.")
        return 3
    if args.dump_signals:
        import csv
        with open(args.dump_signals, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["series", "ticker", "kickoff", "label", "model", "market", "outcome"])
            for sg, lab in zip(signals, labels):
                w.writerow([lab, sg.ticker, sg.kickoff.isoformat(), sg.label,
                            f"{sg.model_fair:.6f}", f"{sg.market_price:.6f}", sg.realized_outcome])
        print(f"Wrote {len(signals)} signals to {args.dump_signals}")
    breakdown(signals, labels)
    print(render_report(run_backtest(signals, KellyConfig.from_policy(DEFAULT_POLICY))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
