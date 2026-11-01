"""SQLite store for the paper in-play run: ticks, quotes, paper trades, structural arbs."""
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS game_ticks (ts REAL, game_id TEXT, league TEXT, home TEXT, away TEXT,
  state TEXT, status TEXT, minute REAL, hs INT, as_ INT, red_h INT, red_a INT);
CREATE TABLE IF NOT EXISTS quotes (ts REAL, game_id TEXT, ticker TEXT, label TEXT,
  yes_bid REAL, yes_ask REAL, bid_sz REAL, ask_sz REAL);
CREATE TABLE IF NOT EXISTS paper_trades (id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL, game_id TEXT,
  ticker TEXT, label TEXT, contract TEXT, line TEXT, side TEXT, kind TEXT,
  fair REAL, entry REAL, size REAL, fee REAL, edge_net REAL, minute REAL, hs INT, as_ INT,
  secs_since_goal REAL, entry_delayed REAL, fee_delayed REAL,
  result_yes INT, pnl REAL, pnl_delayed REAL);
CREATE TABLE IF NOT EXISTS arbs (ts REAL, game_id TEXT, kind TEXT, detail TEXT,
  cost REAL, payout REAL, fees REAL, net REAL, size REAL);
"""


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
