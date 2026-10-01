"""Live-gated backtest entrypoint (design §4 component 8).

Pulls real historical Kalshi soccer markets + candlesticks + settlement, replays
the goal model at a pre-close time *without lookahead*, and prints the backtest
report. Degrades gracefully with a clear message if historical data is unreachable
— correctness of the harness itself is covered by the synthetic validation tests.

Usage:
    python scripts/run_edge_backtest.py [--db data/football.sqlite] [--limit 200]
                                   [--lead-hours 1] [--since 2016-01-01] [--model mle|goal]
"""
import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

from kalshi_edge.config import KALSHI_BASE_URL, SOCCER_SERIES_TICKERS
from kalshi_edge.kalshi.http import KalshiHTTP
from kalshi_edge.kalshi.client import KalshiClient
from kalshi_edge.data.cache import connect
from kalshi_edge.backtest.replay import (
    HistoricalMarket, parse_contract, replay_market, LookaheadError,
)
from kalshi_edge.backtest.harness import run_backtest, render_report
from kalshi_edge.backtest.edge_metrics import KellyConfig
from kalshi_edge.edge.policy import DEFAULT_POLICY


def _series_of(ticker: str) -> str:
    return (ticker or "").split("-")[0]


# Kalshi gives no kickoff time on soccer markets: ``occurrence_datetime`` /
# ``expected_expiration_time`` are a placeholder near the *end* of the match, so
# "kickoff - lead" lands in-play with the result already priced in. ``close_time``
# is when the result was determined (<= ~3.3h after kickoff even with extra time +
# penalties), so close_time - 3.5h is a conservative pre-match proxy: always before
# real kickoff, hence no lookahead, at the cost of a slightly stale price.
KICKOFF_BEFORE_CLOSE = timedelta(hours=3.5)


def _kickoff(market: dict):
    ts = market.get("close_time")
    if ts:
        return datetime.fromisoformat(ts.replace("Z", "+00:00")) - KICKOFF_BEFORE_CLOSE
    for field in ("occurrence_datetime", "expected_expiration_time"):
        ts = market.get(field)
        if ts:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")) - KICKOFF_BEFORE_CLOSE
    return None


def _settled_yes(market: dict):
    result = (market.get("result") or "").lower()
    if result in ("yes", "no"):
        return result == "yes"
    return None  # unsettled / unknown -> skip


def _resolve_teams(market: dict, model_teams: set[str]) -> tuple[str, str] | None:
    """Best-effort: find model team names mentioned in the market text."""
    text = " ".join(str(market.get(k, "")) for k in ("title", "yes_sub_title", "subtitle"))
    hits = [t for t in model_teams if t and t.lower() in text.lower()]
    hits.sort(key=len, reverse=True)  # prefer longer, more specific names
    return (hits[0], hits[1]) if len(hits) >= 2 else None


def build_signals(client: KalshiClient, conn, series_tickers, *, limit: int,
                  lead_hours: float, since: str | None, model_kind: str = "mle"):
    """Return (signals, stats). Never raises per-market; skips what it can't map."""
    from kalshi_edge.model.strengths import team_strengths
    # Team universe the model knows, for name resolution.
    model_teams = set(team_strengths(conn, ref_date="2100-01-01", since=since)["teams"].keys())

    fits: dict = {}  # ref_date -> fitted model (many markets share a match day)

    def model_for(ref_date: str):
        if ref_date not in fits:
            if model_kind == "mle":
                from kalshi_edge.model.mle_model import MLEGoalModel
                fits[ref_date] = MLEGoalModel.from_db(conn, ref_date=ref_date, since=since)
            else:
                fits[ref_date] = None  # replay_market builds the v1 GoalModel
        return fits[ref_date]

    signals = []
    stats = {"markets": 0, "unmapped": 0, "unsettled": 0, "no_price": 0,
             "lookahead_skips": 0, "signals": 0}
    for series in series_tickers:
        for m in client.get_historical_markets(series_ticker=series, limit=limit):
            stats["markets"] += 1
            kickoff = _kickoff(m)
            settled = _settled_yes(m)
            subtitle = m.get("yes_sub_title") or m.get("subtitle") or ""
            teams = _resolve_teams(m, model_teams)
            if kickoff is None or settled is None or teams is None:
                stats["unsettled"] += 1
                continue
            home, away = teams
            contract = parse_contract(_series_of(m.get("ticker", series)), subtitle, home, away)
            if contract is None:
                stats["unmapped"] += 1
                continue
            ref_date = (kickoff.date() - timedelta(days=1)).isoformat()
            pre_close = kickoff - timedelta(hours=lead_hours)
            pre_close_ts = int(pre_close.timestamp())
            try:
                candles = client.get_historical_candlesticks(
                    m["ticker"], start_ts=int((kickoff - timedelta(days=3)).timestamp()),
                    end_ts=pre_close_ts, period_interval=60)
            except Exception:
                candles = []
            market = HistoricalMarket(
                ticker=m["ticker"], series=_series_of(m.get("ticker", series)),
                home=home, away=away, kickoff=kickoff, contract=contract,
                settled_yes=settled, neutral=True)
            try:
                sig = replay_market(conn, market, ref_date=ref_date,
                                    pre_close_ts=pre_close_ts, candles=candles, since=since,
                                    model=model_for(ref_date))
            except LookaheadError:
                stats["lookahead_skips"] += 1
                continue
            except (ValueError, KeyError):
                stats["unmapped"] += 1
                continue
            if sig is None:
                stats["no_price"] += 1
                continue
            signals.append(sig)
            stats["signals"] += 1
    return signals, stats


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Run the Kalshi soccer backtest harness.")
    p.add_argument("--db", default="data/football.sqlite")
    p.add_argument("--limit", type=int, default=200)
    p.add_argument("--lead-hours", type=float, default=1.0)
    p.add_argument("--since", default="2016-01-01")
    p.add_argument("--model", choices=("mle", "goal"), default="mle",
                   help="mle = opponent-adjusted Dixon-Coles; goal = raw goals-for/against v1")
    args = p.parse_args(argv)

    if not os.path.exists(args.db):
        print(f"Football DB not found at {args.db!r} — run scripts/build_db.py first.")
        return 1

    conn = connect(args.db)
    client = KalshiClient(http=KalshiHTTP(base_url=KALSHI_BASE_URL))
    try:
        signals, stats = build_signals(client, conn, SOCCER_SERIES_TICKERS,
                                       limit=args.limit, lead_hours=args.lead_hours,
                                       since=args.since, model_kind=args.model)
    except Exception as exc:  # network / proxy / API shape — degrade gracefully
        print("Could not reach Kalshi historical data (backtest not run).")
        print(f"  reason: {type(exc).__name__}: {exc}")
        return 2

    print(f"Scanned {stats['markets']} historical markets: {stats['signals']} usable "
          f"signals, {stats['unmapped']} unmapped, {stats['unsettled']} unsettled/"
          f"unresolved, {stats['no_price']} no pre-close price, "
          f"{stats['lookahead_skips']} lookahead-skipped.")
    if not signals:
        print("No usable signals — cannot judge model edge yet.")
        return 3
    print(render_report(run_backtest(signals, KellyConfig.from_policy(DEFAULT_POLICY))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
