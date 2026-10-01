"""Settle logged signals against Kalshi outcomes (paper trading).

``settle_signals`` fills ``result_yes`` / ``outcome`` / ``settled_at`` for rows whose
market has resolved. ``scorecard`` then compares, per series, the model's Brier score
with the *market's* — the benchmark that decides whether the model adds anything —
and reports paper P&L for the signals the policy would actually have bet.
"""
import sqlite3
from collections import defaultdict
from datetime import datetime, timezone
from typing import Callable, Optional

from kalshi_edge.edge.engine import series_of

KALSHI_FEE_RATE = 0.07  # taker fee = ceil-to-cent(0.07 * C * P * (1 - P)); unrounded here


def fee_per_contract(price: float, rate: float = KALSHI_FEE_RATE) -> float:
    return rate * price * (1.0 - price)


def fetch_result(client, ticker: str) -> Optional[bool]:
    """True/False once settled, None if not yet. Tries live, then the archive."""
    for getter in (client.get_market, client.get_historical_market):
        try:
            market = getter(ticker)
        except Exception:  # 404 on the tier that no longer holds it, or transient
            continue
        result = (market.get("result") or "").lower()
        if result in ("yes", "no"):
            return result == "yes"
        if market:
            return None
    return None


def settle_signals(conn: sqlite3.Connection, fetch: Callable[[str], Optional[bool]],
                   now: Optional[datetime] = None) -> dict:
    """Settle every unsettled ticker once. ``fetch(ticker) -> True | False | None``."""
    stamp = (now or datetime.now(timezone.utc)).isoformat()
    tickers = [r[0] for r in conn.execute(
        "SELECT DISTINCT ticker FROM signal_log WHERE result_yes IS NULL")]
    settled = pending = 0
    for t in tickers:
        yes = fetch(t)
        if yes is None:
            pending += 1
            continue
        conn.execute(
            "UPDATE signal_log SET result_yes=?, settled_at=?, "
            "outcome=CASE WHEN side='yes' THEN ? WHEN side='no' THEN ? ELSE NULL END "
            "WHERE ticker=? AND result_yes IS NULL",
            (int(yes), stamp, int(yes), int(not yes), t))
        settled += 1
    conn.commit()
    return {"tickers": len(tickers), "settled": settled, "pending": pending}


def settled_rows(conn: sqlite3.Connection) -> list[dict]:
    """One row per settled ticker (the latest log before settlement) with the raw
    model probability, market probability and truth. Repeated runs of the monitor
    log the same market many times; counting them all would overstate n."""
    rows = conn.execute(
        "SELECT s.* FROM signal_log s JOIN ("
        "  SELECT ticker, MAX(id) AS mid FROM signal_log WHERE result_yes IS NOT NULL "
        "  AND market_implied > 0 GROUP BY ticker) m ON s.id = m.mid").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["series"] = series_of(d["ticker"])
        d["model"] = d["raw_model_fair"] if d.get("raw_model_fair") is not None else d["model_fair"]
        d["market"] = d["market_implied"]
        d["y"] = d["result_yes"]
        out.append(d)
    return out


def paper_pnl(row: dict) -> Optional[float]:
    """Per-contract P&L of buying ``side`` at the logged entry price, net of fees,
    only for signals the policy let through. None if it would not have been bet."""
    if row.get("suppressed") or row.get("entry_price") is None or row.get("outcome") is None:
        return None
    c = row["entry_price"]
    return (1.0 - c if row["outcome"] == 1 else -c) - fee_per_contract(c)


def scorecard(conn: sqlite3.Connection) -> list[dict]:
    """Per-series model-vs-market comparison over settled signals."""
    groups = defaultdict(list)
    for r in settled_rows(conn):
        groups[r["series"]].append(r)
    out = []
    for series, rs in sorted(groups.items()):
        n = len(rs)
        bets = [pnl for pnl in (paper_pnl(r) for r in rs) if pnl is not None]
        out.append({
            "series": series, "n": n,
            "brier_model": sum((r["model"] - r["y"]) ** 2 for r in rs) / n,
            "brier_market": sum((r["market"] - r["y"]) ** 2 for r in rs) / n,
            "bets": len(bets), "paper_pnl_per_contract": (sum(bets) / len(bets)) if bets else None,
        })
    return out


def render_scorecard(rows: list[dict]) -> str:
    if not rows:
        return "No settled signals yet."
    lines = [f"{'series':24} {'n':>5} {'Brier model':>12} {'Brier mkt':>10} {'verdict':>9} {'bets':>5} {'P&L/ct':>8}"]
    for r in rows:
        verdict = "model" if r["brier_model"] < r["brier_market"] else "market"
        pnl = "-" if r["paper_pnl_per_contract"] is None else f"{r['paper_pnl_per_contract']:+.3f}"
        lines.append(f"{r['series']:24} {r['n']:5d} {r['brier_model']:12.4f} "
                     f"{r['brier_market']:10.4f} {verdict:>9} {r['bets']:5d} {pnl:>8}")
    return "\n".join(lines)
