from kalshi_edge.data.cache import connect


def test_connect_creates_expected_tables():
    conn = connect()  # in-memory
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {"matches", "goals", "source_meta"} <= names
