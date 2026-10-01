"""Paper-trading log for the lineup test: one row per (market, model variant).

All variants of a market are priced off the same order book at the same moment, so the
comparison is paired. Settlement reuses the shadow loop's Kalshi result lookup; the
scorecard compares each variant with the unadjusted ``base`` model *and* the market on
the markets both have settled.
"""
import json
import sqlite3
from datetime import datetime, timezone

from kalshi_edge.edge.settle import paper_pnl

SCHEMA = """
CREATE TABLE IF NOT EXISTS lineup_signal (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event TEXT, variant TEXT, ticker TEXT, kickoff TEXT,
    side TEXT, model_fair REAL, market_implied REAL, edge REAL,
    entry_price REAL, fillable_size INTEGER, suppressed INTEGER, suppression_reason TEXT,
    info TEXT, logged_at TEXT,
    result_yes INTEGER, outcome INTEGER, settled_at TEXT,
    UNIQUE (ticker, variant)
);
"""


def ensure_store(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def logged_events(conn) -> set[str]:
    return {r[0] for r in conn.execute("SELECT DISTINCT event FROM lineup_signal")}


def log_variant_signal(conn, sig, logged_at: str | None = None) -> None:
    a = sig.analysis
    info = {k: a[k] for k in ("home_mult", "away_mult", "reason", "home_missing", "away_missing") if k in a}
    conn.execute(
        "INSERT OR IGNORE INTO lineup_signal (event, variant, ticker, kickoff, side, model_fair, "
        "market_implied, edge, entry_price, fillable_size, suppressed, suppression_reason, info, logged_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (a.get("event"), a.get("variant", "base"), sig.ticker, a.get("kickoff"), sig.side, sig.model_fair,
         sig.market_implied, sig.edge, sig.entry_price, sig.fillable_size, int(sig.suppressed),
         sig.suppression_reason, json.dumps(info),
         logged_at or datetime.now(timezone.utc).isoformat()))
    conn.commit()


def settle(conn, fetch) -> dict:
    """``fetch(ticker) -> True | False | None``. Fills result/outcome for resolved tickers."""
    stamp = datetime.now(timezone.utc).isoformat()
    tickers = [r[0] for r in conn.execute(
        "SELECT DISTINCT ticker FROM lineup_signal WHERE result_yes IS NULL")]
    settled = 0
    for t in tickers:
        yes = fetch(t)
        if yes is None:
            continue
        conn.execute(
            "UPDATE lineup_signal SET result_yes=?, settled_at=?, "
            "outcome=CASE WHEN side='yes' THEN ? ELSE ? END WHERE ticker=? AND result_yes IS NULL",
            (int(yes), stamp, int(yes), int(not yes), t))
        settled += 1
    conn.commit()
    return {"tickers": len(tickers), "settled": settled, "pending": len(tickers) - settled}


def scorecard(conn) -> list[dict]:
    """Per non-base variant, on tickers settled for both it and ``base``."""
    rows = [dict(r) for r in conn.execute(
        "SELECT * FROM lineup_signal WHERE result_yes IS NOT NULL AND market_implied > 0")]
    by = {}
    for r in rows:
        by.setdefault(r["variant"], {})[r["ticker"]] = r
    base = by.get("base", {})
    out = []
    for variant in sorted(v for v in by if v != "base"):
        shared = [t for t in by[variant] if t in base]
        n = len(shared)
        if not n:
            continue
        def brier(rs, key):
            return sum((r[key] - r["result_yes"]) ** 2 for r in rs) / len(rs)
        vs, bs = [by[variant][t] for t in shared], [base[t] for t in shared]
        def pnl(rs):
            p = [x for x in map(paper_pnl, rs) if x is not None]
            return len(p), (sum(p) / len(p) if p else None)
        moved = sum(1 for v, b in zip(vs, bs) if abs(v["model_fair"] - b["model_fair"]) > 1e-9)
        nb_v, pnl_v = pnl(vs)
        nb_b, pnl_b = pnl(bs)
        out.append({"variant": variant, "n": n, "moved": moved,
                    "brier_variant": brier(vs, "model_fair"), "brier_base": brier(bs, "model_fair"),
                    "brier_market": brier(vs, "market_implied"),
                    "bets_variant": nb_v, "pnl_variant": pnl_v, "bets_base": nb_b, "pnl_base": pnl_b})
    return out


def render_scorecard(rows: list[dict]) -> str:
    if not rows:
        return "No settled lineup-test markets yet."
    fmt = lambda x: "-" if x is None else f"{x:+.3f}"
    lines = [f"{'variant':10} {'n':>5} {'moved':>6} {'Brier var':>10} {'Brier base':>11} {'Brier mkt':>10} "
             f"{'bets v/b':>9} {'P&L/ct v':>9} {'P&L/ct b':>9}"]
    for r in rows:
        lines.append(f"{r['variant']:10} {r['n']:5d} {r['moved']:6d} {r['brier_variant']:10.4f} "
                     f"{r['brier_base']:11.4f} {r['brier_market']:10.4f} "
                     f"{r['bets_variant']:>4}/{r['bets_base']:<4} {fmt(r['pnl_variant']):>9} {fmt(r['pnl_base']):>9}")
    return "\n".join(lines)
