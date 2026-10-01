"""Kalshi vs Polymarket arbitrage: totals, spreads and soccer 3-way (read-only).

Team sports (NFL/NBA/NHL/MLB), matched like arb_cross_venue.py (team codes + start time):
  Every leg is a one-sided claim about a quantity X (X = margin of Polymarket's first team,
  or the game total): ("gt", c) pays if X > c, ("lt", c) pays if X < c. Lines are x.5 so
  there are no pushes. A "gt c1" leg on one venue plus an "lt c2" leg on the other with
  c2 >= c1 pays >= $1 whatever happens (exactly $1 if c1 == c2; $2 when c1 < X < c2).
Soccer (EPL/La Liga/Bundesliga/Ligue1/MLS/UCL/UEL, 90-minute result):
  buy each of home/draw/away on whichever venue is cheaper; profitable if the cheapest-leg
  total (plus fees) is under $1.
Fees: Kalshi 0.07*p*(1-p); Polymarket taker 0.05*p*(1-p). Top-of-book only.
Run:  python scripts/arb_cross_venue_ext.py [--top 12]
"""
import argparse
import json
import re
from datetime import date, timedelta

import httpx

from arb_cross_venue import G, MONTHS, fee, kdate, num, parse_ts, same  # noqa: E402
from kalshi_edge.config import KALSHI_BASE_URL
from kalshi_edge.kalshi.client import KalshiClient
from kalshi_edge.kalshi.http import KalshiHTTP

TEAM = {"NFL": "nfl", "NBA": "nba", "NHL": "nhl", "MLB": "mlb"}
SOCCER = {"EPL": "epl", "LALIGA": "lal", "BUNDESLIGA": "bun", "LIGUE1": "fl1", "MLS": "mls",
          "UCL": "ucl", "UEL": "uel"}
PFEE = 0.05


def kfee(p):
    return fee(p)


def pfee(p):
    return PFEE * p * (1 - p)


def legs_from_pair(venue, kind, c, bid, ask, bsz, asz):
    """A binary 'X > c' market quote -> its two legs: gt (buy YES) and lt (buy NO)."""
    ff = kfee if venue == "K" else pfee
    return [(venue, "gt", c, ask, asz, ff), (venue, "lt", c, 1 - bid, bsz, ff)]


def best_pairs(legs):
    out = []
    for v1, k1, c1, a1, s1, f1 in legs:
        if k1 != "gt" or a1 is None or a1 <= 0:
            continue
        for v2, k2, c2, a2, s2, f2 in legs:
            if k2 != "lt" or v2 == v1 or a2 is None or a2 <= 0 or c2 < c1:
                continue
            out.append((1 - a1 - a2 - f1(a1) - f2(a2), 1 - a1 - a2, v1, c1, a1, v2, c2, a2,
                        min(s1 or 0, s2 or 0)))
    return out


def kclient():
    return KalshiClient(http=KalshiHTTP(base_url=KALSHI_BASE_URL, timeout=30.0, max_retries=4))


def team_sports(sports, kc):
    results, checked = [], 0
    for lg, sp in TEAM.items():
        poly = []
        for e in httpx.get(G + "/events", params={"series_id": sports[sp], "active": "true",
                                                  "closed": "false", "limit": 500}, timeout=60).json():
            m = re.match(rf"{sp}-([a-z0-9]+)-([a-z0-9]+)-\d{{4}}-\d\d-\d\d$", e.get("slug", ""))
            if m:
                poly.append((m[1], m[2], parse_ts(e.get("startTime")), e["markets"]))
        kg, kt, ks = {}, {}, {}
        for ser, store in ((f"KX{lg}GAME", kg), (f"KX{lg}TOTAL", kt), (f"KX{lg}SPREAD", ks)):
            for mk in kc.iter_markets(series_ticker=ser, status="open", limit=1000):
                store.setdefault(mk["event_ticker"].split("-", 1)[1], []).append(mk)
        for suffix, games in kg.items():
            if len(games) != 2:
                continue
            codes = [m["ticker"].rsplit("-", 1)[1] for m in games]
            exp = parse_ts(games[0].get("expected_expiration_time"))
            hit = next(((a, b, mk) for a, b, st, mk in poly if exp and st and
                        timedelta(hours=1) <= exp - st <= timedelta(hours=6) and
                        ((same(a, codes[0]) and same(b, codes[1])) or
                         (same(a, codes[1]) and same(b, codes[0])))), None)
            if not hit:
                continue
            a, b, pmarkets = hit
            acode = codes[0] if same(a, codes[0]) else codes[1]   # Kalshi code of Polymarket team a
            ml = next((m for m in pmarkets if m.get("sportsMarketType") == "moneyline"), None)
            names = json.loads(ml["outcomes"]) if ml else None
            # --- totals ---
            legs = []
            for m in kt.get(suffix, []):
                if m.get("floor_strike") is None:
                    continue
                bid, ask = num(m["yes_bid_dollars"]), num(m["yes_ask_dollars"])
                if bid is not None and ask is not None and ask > 0:
                    legs += legs_from_pair("K", "tot", m["floor_strike"], bid, ask,
                                           num(m.get("yes_bid_size_fp")), num(m.get("yes_ask_size_fp")))
            for m in pmarkets:
                if m.get("sportsMarketType") == "totals" and m.get("line") is not None:
                    bid, ask = num(m.get("bestBid")), num(m.get("bestAsk"))
                    if bid is not None and ask is not None and ask > 0 and json.loads(m["outcomes"])[0] == "Over":
                        legs += legs_from_pair("P", "tot", m["line"], bid, ask, None, None)
            for r in best_pairs(legs):
                results.append((*r[:2], "total", suffix, r[2:]))
            checked += 1
            # --- spreads (X = margin of Polymarket team a) ---
            legs = []
            for m in ks.get(suffix, []):
                bid, ask = num(m["yes_bid_dollars"]), num(m["yes_ask_dollars"])
                code = m["ticker"].rsplit("-", 1)[1]
                code = re.sub(r"\d+$", "", code)
                if m.get("floor_strike") is None or bid is None or ask is None or ask <= 0:
                    continue
                x = m["floor_strike"]
                if same(code, acode):          # YES: M > x
                    legs += legs_from_pair("K", "sp", x, bid, ask, num(m.get("yes_bid_size_fp")), num(m.get("yes_ask_size_fp")))
                else:                          # YES: -M > x  <=>  M < -x
                    legs += [("K", "lt", -x, ask, num(m.get("yes_ask_size_fp")), kfee),
                             ("K", "gt", -x, 1 - bid, num(m.get("yes_bid_size_fp")), kfee)]
            for m in pmarkets:
                if m.get("sportsMarketType") == "spreads" and m.get("line") is not None:
                    outs = json.loads(m["outcomes"])
                    bid, ask = num(m.get("bestBid")), num(m.get("bestAsk"))
                    if names and outs[0] != names[0] or bid is None or ask is None or ask <= 0:
                        continue               # outcome order differs from moneyline: skip, don't guess
                    # outcome0 (team a, line l) covers if M > -l ; outcome1 covers if M < -l
                    legs += [("P", "gt", -m["line"], ask, None, pfee), ("P", "lt", -m["line"], 1 - bid, None, pfee)]
            for r in best_pairs(legs):
                results.append((*r[:2], "spread", suffix, r[2:]))
            checked += 1
    return results, checked


def soccer(sports, kc):
    results, checked, unmatched = [], 0, 0
    for lg, sp in SOCCER.items():
        poly = []
        if sp not in sports:
            continue
        for e in httpx.get(G + "/events", params={"series_id": sports[sp], "active": "true",
                                                  "closed": "false", "limit": 500}, timeout=60).json():
            m = re.match(rf"{sp}-([a-z0-9]+)-([a-z0-9]+)-(\d{{4}})-(\d\d)-(\d\d)$", e.get("slug", ""))
            if m:
                poly.append((m[1], m[2], date(int(m[3]), int(m[4]), int(m[5])), e["markets"]))
        kg = {}
        for mk in kc.iter_markets(series_ticker=f"KX{lg}GAME", status="open", limit=1000):
            kg.setdefault(mk["event_ticker"], []).append(mk)
        for et, ms in kg.items():
            if len(ms) != 3:
                continue
            d = kdate(et)
            codes = [m["ticker"].rsplit("-", 1)[1] for m in ms if not m["ticker"].endswith("-TIE")]
            hit = next(((a, b, pm) for a, b, pd, pm in poly if d and abs((pd - d).days) <= 1 and
                        ((same(a, codes[0]) and same(b, codes[1])) or (same(a, codes[1]) and same(b, codes[0])))), None)
            if not hit:
                unmatched += 1
                continue
            a, b, pm = hit
            pml = [m for m in pm if m.get("sportsMarketType") == "moneyline"]
            if len(pml) != 3:
                unmatched += 1
                continue
            plegs = {}
            for m in pml:
                q = m["question"].lower()
                key = "TIE" if "draw" in q else None
                plegs[m["question"]] = (key, num(m.get("bestBid")), num(m.get("bestAsk")))
            # map Polymarket win markets to Kalshi codes via order: slug team a / team b appear in question text
            qs = list(plegs)
            tie_q = next(q for q in qs if plegs[q][0] == "TIE")
            win_qs = [q for q in qs if q != tie_q]
            # Kalshi market per outcome
            cost, parts = 0.0, []
            ok = True
            for k in ms:
                code = k["ticker"].rsplit("-", 1)[1]
                ka = num(k["yes_ask_dollars"])
                if code == "TIE":
                    pa = plegs[tie_q][2]
                else:
                    # Kalshi title is e.g. "Arsenal vs Leeds Winner?"; match team by subtitle token in Poly question
                    sub = (k.get("yes_sub_title") or "").lower()
                    cand = [q for q in win_qs if sub and sub.split()[0] in q.lower()]
                    pa = plegs[cand[0]][2] if len(cand) == 1 else None
                if ka is None or pa is None or pa <= 0 or ka <= 0:
                    ok = False
                    break
                cheaper = min((ka + kfee(ka), "K"), (pa + pfee(pa), "P"))
                cost += cheaper[0]
                parts.append(f"{code}:{cheaper[1]}@{ka if cheaper[1]=='K' else pa:.2f}")
            if not ok:
                unmatched += 1
                continue
            checked += 1
            results.append((1 - cost, 1 - cost, "soccer3", et, tuple(parts)))
    return results, checked, unmatched


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=12)
    args = ap.parse_args()
    kc = kclient()
    sports = {s["sport"]: s["series"] for s in httpx.get(G + "/sports", timeout=30).json()}
    rows, n1 = team_sports(sports, kc)
    srows, n2, un = soccer(sports, kc)
    rows += srows
    rows.sort(key=lambda r: -r[0])
    print(f"team-sport games priced for totals/spreads: {n1 // 2}; soccer 3-way sets priced: {n2} (unmatched {un})")
    print(f"candidate hedges: {len(rows)}; profitable after both venues' fees: {sum(1 for r in rows if r[0] > 0)}\n")
    for net, gross, kind, ev, d in rows[:args.top]:
        print(f"  net {net:+.3f} (gross {gross:+.3f})  {kind:7} {ev}  {d}")


if __name__ == "__main__":
    main()
