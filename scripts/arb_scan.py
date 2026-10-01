"""Read-only live arbitrage scan on mutually exclusive soccer moneyline sets.

For every open KX<league>GAME event with all 3 outcomes (home / away / Tie):
  * buy YES on all three: pays exactly $1, costs sum(best YES asks) + fees
  * buy NO on all three:  pays exactly $2, costs sum(best NO asks)  + fees
An arb exists when the all-in cost is below the payout. Prints the closest
events either way, so "none found" still shows how far the book is from one.

Usage: python scripts/arb_scan.py [--top 10]
"""
import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from kalshi_edge.config import CLUB_LEAGUES, KALSHI_BASE_URL
from kalshi_edge.kalshi.client import KalshiClient
from kalshi_edge.kalshi.http import KalshiHTTP
from kalshi_edge.kalshi.orderbook import effective_prices


def client():
    return KalshiClient(http=KalshiHTTP(base_url=KALSHI_BASE_URL, timeout=20.0, max_retries=4))


def fee(p):
    return 0.07 * p * (1 - p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=10)
    args = ap.parse_args()
    events = defaultdict(list)
    for lg in CLUB_LEAGUES:
        for m in client().iter_markets(series_ticker=f"KX{lg}GAME", status="open"):
            events[m["event_ticker"]].append(m["ticker"])
    full = {e: t for e, t in events.items() if len(t) == 3}
    print(f"{len(events)} open events, {len(full)} with a full 3-way set")

    def book(t):
        try:
            return effective_prices(client().get_orderbook(t))
        except Exception:
            return None

    rows = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        for e, tickers in full.items():
            ps = list(pool.map(book, tickers))
            if any(p is None or p.yes_ask is None or p.yes_bid is None for p in ps):
                continue
            ya = sum(p.yes_ask for p in ps)
            na = sum(1 - p.yes_bid for p in ps)
            yes_edge = 1 - ya - sum(fee(p.yes_ask) for p in ps)
            no_edge = 2 - na - sum(fee(1 - p.yes_bid) for p in ps)
            rows.append((max(yes_edge, no_edge), e, ya, sum(p.yes_bid for p in ps), yes_edge, no_edge))
    rows.sort(reverse=True)
    arbs = [r for r in rows if r[0] > 0]
    print(f"{len(rows)} priced sets, {len(arbs)} arbitrages after fees\n")
    print(f"{'event':34} {'sum ask':>8} {'sum bid':>8} {'all-YES':>8} {'all-NO':>8}  (profit per $1 payout set, after fees)")
    for _, e, ya, yb, ye, ne in rows[:args.top]:
        print(f"{e:34} {ya:8.3f} {yb:8.3f} {ye:+8.3f} {ne:+8.3f}")


if __name__ == "__main__":
    main()
