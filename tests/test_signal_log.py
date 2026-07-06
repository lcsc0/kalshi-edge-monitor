from kalshi_edge.data.cache import connect
from kalshi_edge.edge.engine import EdgeSignal
from kalshi_edge.edge.signal_log import ensure_table, log_signal, realized_hit_rate


def _sig(ticker="MKT", edge=0.06, suppressed=False):
    return EdgeSignal(
        ticker=ticker, side="yes", model_fair=0.62, market_implied=0.56,
        edge=edge, fillable_size=100, slippage=0.0, suppressed=suppressed,
        suppression_reason=None,
        analysis={"home": "Strong", "away": "Weak"})


def test_ensure_table_creates_signal_log():
    conn = connect()
    ensure_table(conn)
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert "signal_log" in names


def test_log_signal_persists_inputs():
    conn = connect()
    ensure_table(conn)
    log_signal(conn, _sig(), fetched_at="2026-07-06T12:00:00Z")
    row = conn.execute("SELECT ticker, side, edge, model_fair, suppressed, "
                       "fetched_at, logged_at FROM signal_log").fetchone()
    assert row["ticker"] == "MKT"
    assert row["side"] == "yes"
    assert abs(row["edge"] - 0.06) < 1e-9
    assert row["suppressed"] == 0
    assert row["fetched_at"] == "2026-07-06T12:00:00Z"
    assert row["logged_at"]  # a timestamp was stamped


def test_realized_hit_rate_accrues_from_settled_rows():
    conn = connect()
    ensure_table(conn)
    log_signal(conn, _sig("A"), fetched_at="t")
    log_signal(conn, _sig("B"), fetched_at="t")
    log_signal(conn, _sig("C"), fetched_at="t")
    # settle outcomes: A, B win; C loses
    conn.execute("UPDATE signal_log SET outcome=1 WHERE ticker IN ('A','B')")
    conn.execute("UPDATE signal_log SET outcome=0 WHERE ticker='C'")
    conn.commit()
    assert abs(realized_hit_rate(conn) - 2 / 3) < 1e-9


def test_realized_hit_rate_none_without_settled_rows():
    conn = connect()
    ensure_table(conn)
    log_signal(conn, _sig(), fetched_at="t")
    assert realized_hit_rate(conn) is None
