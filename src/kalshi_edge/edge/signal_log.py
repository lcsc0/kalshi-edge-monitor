"""Forward signal log (design §3).

Every emitted signal is persisted with its inputs so a realized hit-rate can
accrue from day one and later feed calibration. Rows live in the same SQLite
database as the SP2a data cache (reuse ``kalshi_edge.data.cache.connect``); this
module owns its own ``signal_log`` table and creates it on demand, so it does not
depend on edits to ``cache.py``.
"""
import json
import sqlite3
from datetime import datetime, timezone

from kalshi_edge.edge.engine import EdgeSignal

SCHEMA = """
CREATE TABLE IF NOT EXISTS signal_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT,
    side TEXT,
    model_fair REAL,
    market_implied REAL,
    edge REAL,
    fillable_size INTEGER,
    slippage REAL,
    suppressed INTEGER,
    suppression_reason TEXT,
    analysis TEXT,
    fetched_at TEXT,
    logged_at TEXT,
    outcome INTEGER            -- NULL until the market settles: 1=win, 0=loss
);
"""


def ensure_table(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def log_signal(conn: sqlite3.Connection, signal: EdgeSignal,
               fetched_at: str, logged_at: str | None = None) -> None:
    """Persist a single :class:`EdgeSignal` with its inputs and timestamps."""
    logged_at = logged_at or datetime.now(timezone.utc).isoformat()
    conn.execute(
        "INSERT INTO signal_log (ticker, side, model_fair, market_implied, edge, "
        "fillable_size, slippage, suppressed, suppression_reason, analysis, "
        "fetched_at, logged_at, outcome) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)",
        (signal.ticker, signal.side, signal.model_fair, signal.market_implied,
         signal.edge, signal.fillable_size, signal.slippage,
         1 if signal.suppressed else 0, signal.suppression_reason,
         json.dumps(signal.analysis), fetched_at, logged_at),
    )
    conn.commit()


def realized_hit_rate(conn: sqlite3.Connection) -> float | None:
    """Fraction of *settled, non-suppressed* signals that settled in-the-money.

    Returns ``None`` when no settled rows exist yet.
    """
    row = conn.execute(
        "SELECT AVG(outcome) AS rate FROM signal_log "
        "WHERE outcome IS NOT NULL AND suppressed = 0").fetchone()
    return None if row["rate"] is None else float(row["rate"])
