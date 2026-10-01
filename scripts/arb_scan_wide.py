"""Read-only multi-sport arbitrage scan using top-of-book from the bulk market list.

Checks, all risk-free if the quotes are real and fillable:
  1. Complete sets (GAME / MATCH series, soccer 3-way, others 2-way):
       buy YES on every outcome  -> pays $1,      cost sum(ask)
       buy NO  on every outcome  -> pays $(n-1),  cost sum(1-bid)
  2. Ladders (TOTAL / SPREAD / TEAMTOTAL / 1H): "over k2" implies "over k1" for k1<k2,
       so bid(k2) must not exceed ask(k1). Violation: buy YES k1 + buy NO k2, pays >= $1,
       costs ask(k1) + 1 - bid(k2).
Taker fee modelled as 0.07*p*(1-p) per contract per leg (unrounded; real fees round up).

Usage: python scripts/arb_scan_wide.py [--top 15]
"""
import argparse
import json
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from kalshi_edge.config import KALSHI_BASE_URL
from kalshi_edge.kalshi.client import KalshiClient
from kalshi_edge.kalshi.http import KalshiHTTP

LEAGUES = ["NFL", "NBA", "MLB", "NHL", "NCAAF", "WNBA", "MLS", "UCL", "UEL", "EPL",
           "LALIGA", "SERIEA", "BUNDESLIGA", "LIGUE1"]
SETS = [f"KX{lg}GAME" for lg in LEAGUES] + ["KXATPMATCH", "KXWTAMATCH"]
LADDERS = [f"KX{lg}{k}" for lg in LEAGUES for k in ("TOTAL", "SPREAD", "TEAMTOTAL", "1H", "BTTS")]


def fee(p):
    return 0.07 * p * (1 - p)


def f(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def quote(m):
    return (f(m.get("yes_bid_dollars")), f(m.get("yes_ask_dollars")),
            f(m.get("yes_bid_size_fp")), f(m.get("yes_ask_size_fp")))


def pull(series):
    c = KalshiClient(http=KalshiHTTP(base_url=KALSHI_BASE_URL, timeout=30.0, max_retries=4))
    try:
        return series, list(c.iter_markets(series_ticker=series, status="open", limit=1000))
    except Exception:
        return series, []


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args()
    with ThreadPoolExecutor(8) as pool:
        data = dict(pool.map(pull, SETS + LADDERS))
    print("markets pulled:", sum(len(v) for v in data.values()))

    found = []  # (net profit per set, kind, desc, size)
    near = []
    # 1. complete sets
    for s in SETS:
        ev = defaultdict(list)
        for m in data[s]:
            ev[m["event_ticker"]].append(m)
        for e, ms in ev.items():
            n = len(ms)
            soccer = any(l in s for l in ("MLS", "UCL", "UEL", "EPL", "LALIGA", "SERIEA", "BUNDESLIGA", "LIGUE1"))
            if n != (3 if soccer else 2):
                continue
            qs = [quote(m) for m in ms]
            if any(x[0] is None or x[1] is None or x[1] <= 0 for x in qs):
                continue
            yes_cost = sum(x[1] for x in qs) + sum(fee(x[1]) for x in qs)
            no_cost = sum(1 - x[0] for x in qs) + sum(fee(1 - x[0]) for x in qs)
            size_y = min(x[3] or 0 for x in qs)
            size_n = min(x[2] or 0 for x in qs)
            for kind, prof, size in (("all-YES", 1 - yes_cost, size_y), ("all-NO", (n - 1) - no_cost, size_n)):
                (found if prof > 0 else near).append((prof, f"set {kind}", e, size))
    # 2. ladders
    for s in LADDERS:
        groups = defaultdict(list)
        for m in data[s]:
            if m.get("strike_type") != "greater" or m.get("floor_strike") is None:
                continue
            key = (m["event_ticker"], json.dumps(m.get("custom_strike"), sort_keys=True),
                   re.sub(r"[\d.]+", "#", m.get("yes_sub_title") or ""))
            groups[key].append(m)
        for key, ms in groups.items():
            ms.sort(key=lambda m: m["floor_strike"])
            for lo, hi in zip(ms, ms[1:]):
                bl, al, _, asz = quote(lo)
                bh, ah, bsz, _ = quote(hi)
                if al is None or bh is None or al <= 0 or bh <= 0:
                    continue
                prof = bh - al - fee(al) - fee(1 - bh)
                rec = (prof, "ladder", f"{hi['ticker']} bid {bh:.2f} > {lo['ticker']} ask {al:.2f}",
                       min(asz or 0, bsz or 0))
                (found if prof > 0 else near).append(rec)
    found.sort(reverse=True)
    near.sort(reverse=True)
    print(f"\nARBITRAGES AFTER FEES: {len(found)}")
    for p, k, d, sz in found[:args.top]:
        print(f"  {p:+.3f}/set  size~{sz:.0f}  {k}: {d}")
    print(f"\nclosest misses ({len(near)} candidates checked):")
    for p, k, d, sz in near[:args.top]:
        print(f"  {p:+.3f}/set  size~{sz:.0f}  {k}: {d}")


if __name__ == "__main__":
    main()
