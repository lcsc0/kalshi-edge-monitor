"""Favorite-longshot-bias test on settled Kalshi club-soccer moneyline markets.

No model: for every settled KX<league>GAME market take the pre-kickoff quote
and the realized result, then ask whether cheap contracts (longshots) lose
more per dollar than expensive ones (favorites) -- and whether anything is
profitable after the taker fee.

Kickoff is not in the market record. Moneyline markets close at the final
whistle, so kickoff ~= close_time - 2h05m; the quote is the last hourly candle
ending at least ``--lead-hours`` before that estimated kickoff.

Usage: python scripts/flb_test.py [--lead-hours 1] [--workers 8] [--out flb.csv]
"""
import argparse
import csv
import json
import math
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from kalshi_edge.config import CLUB_LEAGUES, KALSHI_BASE_URL
from kalshi_edge.kalshi.client import KalshiClient
from kalshi_edge.kalshi.http import KalshiHTTP

GAME_LEN_S = int(2 * 3600 + 5 * 60)


def client() -> KalshiClient:
    return KalshiClient(http=KalshiHTTP(base_url=KALSHI_BASE_URL, timeout=30.0, max_retries=5))


def ts(s: str) -> float:
    return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def fee(p: float) -> float:
    """Kalshi taker fee per $1 contract: 0.07 * p * (1 - p)."""
    return 0.07 * p * (1 - p)


def quote(candles, cutoff):
    last = None
    for c in candles:
        if c["end_period_ts"] <= cutoff:
            last = c
    if not last:
        return None
    try:
        bid, ask = float(last["yes_bid"]["close"]), float(last["yes_ask"]["close"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (0 < bid <= ask < 1) or ask - bid > 0.10:  # empty / absurdly wide book
        return None
    return bid, ask, float(last["volume"] or 0)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lead-hours", type=float, default=1.0)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--cache", default="data/flb_candles.json")
    ap.add_argument("--out", default="data/flb_rows.csv")
    args = ap.parse_args()

    markets = []
    for lg in CLUB_LEAGUES:
        n = 0
        for m in client().iter_historical_markets(series_ticker=f"KX{lg}GAME"):
            if (m.get("result") or "").lower() in ("yes", "no") and m.get("close_time"):
                markets.append((lg, m))
                n += 1
        print(f"{lg}: {n} settled GAME markets")

    cache = json.load(open(args.cache)) if os.path.exists(args.cache) else {}

    def fetch(item):
        lg, m = item
        close = ts(m["close_time"])
        kick = close - GAME_LEN_S
        try:
            return client().get_historical_candlesticks(
                m["ticker"], start_ts=int(kick - 3 * 86400),
                end_ts=int(kick - args.lead_hours * 3600), period_interval=60)
        except Exception:
            return None

    todo = [it for it in markets if it[1]["ticker"] not in cache]
    print(f"{len(markets) - len(todo)} cached, fetching {len(todo)} candle sets")
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for it, res in zip(todo, pool.map(fetch, todo)):
            if res is not None:
                cache[it[1]["ticker"]] = res
    os.makedirs(os.path.dirname(args.cache) or ".", exist_ok=True)
    json.dump(cache, open(args.cache, "w"))

    rows = []
    for lg, m in markets:
        candles = cache.get(m["ticker"])
        if not candles:
            continue
        cutoff = ts(m["close_time"]) - GAME_LEN_S - args.lead_hours * 3600
        q = quote(candles, cutoff)
        if q is None:
            continue
        bid, ask, vol = q
        rows.append(dict(league=lg, ticker=m["ticker"], event=m["event_ticker"],
                         close=m["close_time"], bid=bid, ask=ask, vol=vol,
                         y=1 if m["result"].lower() == "yes" else 0))
    with open(args.out, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"{len(rows)} usable rows -> {args.out}")
    analyse(rows)
    return 0


BINS = [(0, .05), (.05, .10), (.10, .20), (.20, .35), (.35, .50), (.50, .65),
        (.65, .80), (.80, .90), (.90, 1.0)]


def analyse(rows):
    for r in rows:
        r["mid"] = (r["bid"] + r["ask"]) / 2
    print(f"\nOverall: n={len(rows)}  mean implied={sum(r['mid'] for r in rows)/len(rows):.4f}  "
          f"realized={sum(r['y'] for r in rows)/len(rows):.4f}")
    print("\nCalibration by mid-price bin (n, implied, realized, z), then $ return per $1 contract")
    print("buying YES at ask / buying NO at 1-bid, before and after taker fee.")
    hdr = (f"{'bin':>9} {'n':>5} {'implied':>7} {'real':>7} {'z':>6} | "
           f"{'YES gross':>9} {'YES net':>8} | {'NO gross':>8} {'NO net':>8}")
    print(hdr)
    for lo, hi in BINS:
        v = [r for r in rows if lo <= r["mid"] < hi]
        if not v:
            continue
        n = len(v)
        imp = sum(r["mid"] for r in v) / n
        real = sum(r["y"] for r in v) / n
        se = math.sqrt(max(imp * (1 - imp), 1e-9) / n)
        yg = sum(r["y"] - r["ask"] for r in v) / n
        yn = sum(r["y"] - r["ask"] - fee(r["ask"]) for r in v) / n
        ng = sum((1 - r["y"]) - (1 - r["bid"]) for r in v) / n
        nn = sum((1 - r["y"]) - (1 - r["bid"]) - fee(1 - r["bid"]) for r in v) / n
        print(f"{lo:.2f}-{hi:.2f} {n:5d} {imp:7.3f} {real:7.3f} {(real-imp)/se:6.2f} | "
              f"{yg:+9.4f} {yn:+8.4f} | {ng:+8.4f} {nn:+8.4f}")

    # Longshots vs favourites, per-dollar staked (return on capital).
    def roi(v, side, with_fee):
        cost = pnl = 0.0
        for r in v:
            p = r["ask"] if side == "yes" else 1 - r["bid"]
            win = r["y"] if side == "yes" else 1 - r["y"]
            f = fee(p) if with_fee else 0.0
            cost += p + f
            pnl += win - p - f
        return pnl / cost if cost else float("nan"), len(v)

    print("\nReturn on capital:")
    for name, test in [("longshot YES  mid<0.15", lambda r: r["mid"] < .15),
                       ("favourite YES mid>0.70", lambda r: r["mid"] > .70)]:
        v = [r for r in rows if test(r)]
        print(f"  {name}: gross {roi(v,'yes',False)[0]:+.2%}  net {roi(v,'yes',True)[0]:+.2%}  (n={len(v)})")
    for name, test in [("fade longshot (buy NO) mid<0.15", lambda r: r["mid"] < .15),
                       ("fade favourite (buy NO) mid>0.70", lambda r: r["mid"] > .70)]:
        v = [r for r in rows if test(r)]
        print(f"  {name}: gross {roi(v,'no',False)[0]:+.2%}  net {roi(v,'no',True)[0]:+.2%}  (n={len(v)})")


if __name__ == "__main__":
    raise SystemExit(main())
