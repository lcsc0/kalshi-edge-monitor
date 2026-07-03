import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    date TEXT, home_team TEXT, away_team TEXT,
    home_score INTEGER, away_score INTEGER,
    tournament TEXT, city TEXT, country TEXT, neutral INTEGER
);
CREATE TABLE IF NOT EXISTS goals (
    date TEXT, home_team TEXT, away_team TEXT, team TEXT,
    scorer TEXT, minute INTEGER, own_goal INTEGER, penalty INTEGER
);
CREATE TABLE IF NOT EXISTS source_meta (
    source TEXT PRIMARY KEY, fetched_at TEXT, row_count INTEGER
);
CREATE INDEX IF NOT EXISTS idx_matches_home ON matches(home_team);
CREATE INDEX IF NOT EXISTS idx_matches_away ON matches(away_team);
CREATE INDEX IF NOT EXISTS idx_goals_scorer ON goals(scorer);
"""


def connect(path: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
