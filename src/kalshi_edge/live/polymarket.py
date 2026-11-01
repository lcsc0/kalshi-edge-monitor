"""Read-only Polymarket access (public gamma + CLOB endpoints). No keys, no orders."""
import json
import re
from datetime import date

import httpx

from kalshi_edge.kalshi.club_match import name_score

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
_SLUG = re.compile(r"^[a-z0-9]{2,5}-[a-z0-9]{2,5}-[a-z0-9]{2,5}-(\d{4})-(\d{2})-(\d{2})$")
_WIN = re.compile(r"^Will (.+?) win on", re.I)


def poly_fee(price: float, shares: float, rate: float = 0.05) -> float:
    """Taker fee in dollars, ASSUMED as shares * rate * p * (1-p) from the market's
    feeSchedule {rate: 0.05, exponent: 1, takerOnly}. Verify against a real fill."""
    return shares * rate * price * (1.0 - price)


def find_match_event(client: httpx.Client, home: str, away: str, day: date) -> dict | None:
    """Gamma event for home v away on ``day`` (+/-1) with draw/home/away moneyline markets."""
    body = client.get(f"{GAMMA}/public-search", params={"q": f"{home} {away}", "limit_per_type": 10},
                      timeout=15).json()
    best = None
    for ev in body.get("events", []):
        m = _SLUG.match(ev.get("slug", ""))
        if not m or ev.get("ended"):
            continue
        d = date(int(m[1]), int(m[2]), int(m[3]))
        if abs((d - day).days) > 1:
            continue
        legs = {}
        for mk in ev.get("markets", []):
            if mk.get("sportsMarketType") != "moneyline" or mk.get("closed"):
                continue
            q = mk["question"]
            toks = json.loads(mk["clobTokenIds"])
            if "draw" in q.lower():
                legs["draw"] = toks[0]
                continue
            w = _WIN.match(q)
            if not w:
                continue
            sh, sa = name_score(w[1], home), name_score(w[1], away)
            if max(sh, sa) >= 0.6:
                legs["home" if sh >= sa else "away"] = toks[0]
        if len(legs) == 3:
            return {"slug": ev["slug"], "tokens": legs}
    return best


def top_of_book(client: httpx.Client, tokens: dict[str, str]) -> dict[str, dict]:
    """{'home': {bid, ask, bid_sz, ask_sz}, ...} via the batch /books endpoint."""
    r = client.post(f"{CLOB}/books", json=[{"token_id": t} for t in tokens.values()], timeout=10)
    r.raise_for_status()
    by_tok = {b["asset_id"]: b for b in r.json()}
    out = {}
    for name, tok in tokens.items():
        b = by_tok.get(tok)
        if not b:
            continue
        bids = [(float(x["price"]), float(x["size"])) for x in b.get("bids", [])]
        asks = [(float(x["price"]), float(x["size"])) for x in b.get("asks", [])]
        bb = max(bids) if bids else (None, 0.0)
        ba = min(asks) if asks else (None, 0.0)
        out[name] = {"bid": bb[0], "bid_sz": bb[1], "ask": ba[0], "ask_sz": ba[1]}
    return out
