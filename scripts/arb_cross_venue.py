"""Read-only Kalshi vs Polymarket moneyline arbitrage scan (US team sports).

Games are matched on (team abbreviation pair, start time: Kalshi expected expiration is
1-6h after Polymarket startTime -- a +/-1 day date match pairs different games of the
same MLB/NHL series and produces phantom arbs): Kalshi tickers end in
the team code (KXNFLGAME-26OCT05ATLNO-ATL); Polymarket slugs look like
nfl-sea-was-2026-09-27 with outcomes in slug order. For each matched game, both
hedges are priced from top-of-book:
    buy Team A YES on Kalshi  +  buy Team B on Polymarket   (pays exactly $1)
    buy Team B YES on Kalshi  +  buy Team A on Polymarket
Polymarket ask for outcome 1 is derived as 1 - bid(outcome 0) (binary complement).
Fees modelled: Kalshi 0.07*p*(1-p); Polymarket taker 0.05*p*(1-p) (feeSchedule rate 0.05).

Usage: python scripts/arb_cross_venue.py [--top 15]
"""
import argparse
import json
import re
from datetime import date, datetime, timedelta

import httpx

from kalshi_edge.config import KALSHI_BASE_URL
from kalshi_edge.kalshi.client import KalshiClient
from kalshi_edge.kalshi.http import KalshiHTTP

G = "https://gamma-api.polymarket.com"
LEAGUES = {"NFL": "nfl", "NBA": "nba", "NHL": "nhl", "MLB": "mlb"}
ALIAS = {"was": "wsh", "wsh": "was", "jax": "jac", "jac": "jax", "gb": "gnb", "gnb": "gb",
         "ne": "nwe", "no": "nor", "sf": "sfo", "tb": "tam", "kc": "kan", "lv": "lvr",
         "la": "lar", "nwe": "ne", "nor": "no", "sfo": "sf", "tam": "tb", "kan": "kc"}
MONTHS = {m: i for i, m in enumerate(
    "JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split(), 1)}


def fee(p):
    return 0.07 * p * (1 - p)


def kdate(event_ticker):
    m = re.search(r"-(\d\d)([A-Z]{3})(\d\d)", event_ticker)
    return date(2000 + int(m[1]), MONTHS[m[2]], int(m[3])) if m else None


def same(a, b):
    a, b = a.lower(), b.lower()
    return a == b or ALIAS.get(a) == b


def parse_ts(s):
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def num(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=15)
    args = ap.parse_args()
    kc = KalshiClient(http=KalshiHTTP(base_url=KALSHI_BASE_URL, timeout=30.0, max_retries=4))
    sports = {s["sport"]: s["series"] for s in httpx.get(G + "/sports", timeout=30).json()}

    rows, unmatched, total = [], 0, 0
    for lg, sp in LEAGUES.items():
        poly = []
        evs = httpx.get(G + "/events", params={"series_id": sports[sp], "active": "true",
                                               "closed": "false", "limit": 500}, timeout=60).json()
        for e in evs:
            m = re.match(rf"{sp}-([a-z0-9]+)-([a-z0-9]+)-(\d{{4}})-(\d\d)-(\d\d)$", e.get("slug", ""))
            ml = [x for x in e.get("markets", []) if x.get("sportsMarketType") == "moneyline"]
            if m and ml:
                poly.append((m[1], m[2], parse_ts(e.get("startTime")), ml[0]))
        kev = {}
        for mk in kc.iter_markets(series_ticker=f"KX{lg}GAME", status="open", limit=1000):
            kev.setdefault(mk["event_ticker"], []).append(mk)
        for et, ms in kev.items():
            if len(ms) != 2:
                continue
            total += 1
            d = kdate(et)
            codes = [m["ticker"].rsplit("-", 1)[1] for m in ms]
            hit = None
            exp = parse_ts(ms[0].get("expected_expiration_time"))
            for a, b, st, pm in poly:
                if exp and st and timedelta(hours=1) <= exp - st <= timedelta(hours=6) and (
                        (same(a, codes[0]) and same(b, codes[1])) or
                        (same(a, codes[1]) and same(b, codes[0]))):
                    hit = (a, b, pm)
                    break
            if not hit:
                unmatched += 1
                continue
            a, b, pm = hit
            bid0, ask0 = num(pm.get("bestBid")), num(pm.get("bestAsk"))
            if bid0 is None or ask0 is None:
                continue
            p_ask = {a: ask0, b: 1 - bid0}          # Polymarket cost to buy each team
            for m, code in zip(ms, codes):
                ka = num(m.get("yes_ask_dollars"))
                other = codes[1] if code == codes[0] else codes[0]
                pk = next((k for k in p_ask if same(k, other)), None)
                if ka is None or pk is None or ka <= 0:
                    continue
                gross = 1 - ka - p_ask[pk]
                rows.append((gross - fee(ka) - 0.05 * p_ask[pk] * (1 - p_ask[pk]), gross, lg, et, f"K {code} ask {ka:.2f} + P {pk} ask {p_ask[pk]:.2f}",
                             num(m.get("yes_ask_size_fp"))))
    rows.sort(reverse=True)
    print(f"Kalshi 2-way games {total}, matched to Polymarket {len({r[3] for r in rows})}, unmatched {unmatched}")
    pos = [r for r in rows if r[0] > 0]
    print(f"hedges checked {len(rows)}; profitable after both venues' fees: {len(pos)}\n")
    for net, gross, lg, et, desc, sz in rows[:args.top]:
        print(f"  net {net:+.3f} (gross {gross:+.3f})  ksize~{sz or 0:.0f}  {et}  {desc}")


if __name__ == "__main__":
    main()
