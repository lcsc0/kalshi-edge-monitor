"""Settle logged shadow signals against Kalshi outcomes and print the scorecard.

Run it daily (or after games finish):
    python scripts/settle_signals.py [--db data/football.sqlite] [--min-n 300]

Prints, per series, model Brier vs *market* Brier on settled signals plus paper P&L
for would-be bets, then the blend weights the live monitor will use. The model earns
a non-zero weight (and so any bets) only where it beats the market with confidence.
"""
import argparse
import os
import sys

from kalshi_edge.config import KALSHI_BASE_URL
from kalshi_edge.data.cache import connect
from kalshi_edge.edge.blend import BlendTable
from kalshi_edge.edge.settle import fetch_result, render_scorecard, scorecard, settle_signals
from kalshi_edge.edge.signal_log import ensure_table
from kalshi_edge.kalshi.client import KalshiClient
from kalshi_edge.kalshi.http import KalshiHTTP


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--db", default="data/football.sqlite")
    p.add_argument("--min-n", type=int, default=300, help="settled signals needed before a series can get weight")
    p.add_argument("--no-fetch", action="store_true", help="only print the scorecard")
    args = p.parse_args(argv)
    if not os.path.exists(args.db):
        print(f"{args.db!r} not found.")
        return 1
    conn = connect(args.db)
    ensure_table(conn)
    if not args.no_fetch:
        client = KalshiClient(http=KalshiHTTP(base_url=KALSHI_BASE_URL))
        stats = settle_signals(conn, lambda t: fetch_result(client, t))
        print(f"Settled {stats['settled']} markets, {stats['pending']} still open "
              f"({stats['tickers']} tickers checked).\n")
    print(render_scorecard(scorecard(conn)))
    print("\nBlend weights (model vs market):")
    print(BlendTable.from_db(conn, min_n=args.min_n).summary())
    return 0


if __name__ == "__main__":
    sys.exit(main())
