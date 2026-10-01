"""Our own record of who starts for each team, built from every lineup we fetch.

Free API quota rules out pulling a season of lineups per team, so "who are the regulars"
is learned from the lineups we log ourselves (zero extra requests). Until a team has
``min_games`` logged lineups it has no regulars, so the statistical adjustment is neutral
for it - the cold start is slow by design, not guessed.
"""
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS lineup_history (
    team TEXT, fixture_id INTEGER, kickoff TEXT,
    player_id INTEGER, player TEXT, pos TEXT,
    PRIMARY KEY (fixture_id, team, player_id)
);
"""


def ensure_history(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


def record_lineup(conn, team: str, fixture_id: int, kickoff_iso: str, lineup) -> None:
    conn.executemany(
        "INSERT OR IGNORE INTO lineup_history VALUES (?,?,?,?,?,?)",
        [(team, fixture_id, kickoff_iso, pid, name, pos) for pid, name, pos in lineup.players])
    conn.commit()


def regulars(conn, team: str, before_iso: str, last_n: int = 10, min_games: int = 3,
             min_share: float = 0.5) -> list[dict]:
    """Players who started >= ``min_share`` of the team's last ``last_n`` logged games
    before ``before_iso``. Empty until ``min_games`` games are logged."""
    games = [r[0] for r in conn.execute(
        "SELECT fixture_id FROM lineup_history WHERE team=? AND kickoff<? "
        "GROUP BY fixture_id ORDER BY MAX(kickoff) DESC LIMIT ?", (team, before_iso, last_n))]
    if len(games) < min_games:
        return []
    marks = ",".join("?" * len(games))
    out = []
    for pid, name, pos, n in conn.execute(
            f"SELECT player_id, player, pos, COUNT(*) FROM lineup_history "
            f"WHERE team=? AND fixture_id IN ({marks}) GROUP BY player_id", (team, *games)):
        if n / len(games) >= min_share:
            out.append({"id": pid, "name": name, "pos": pos, "share": n / len(games)})
    return sorted(out, key=lambda r: -r["share"])


def missing_regulars(conn, team: str, lineup, before_iso: str, **kw) -> list[dict]:
    """Regulars absent from today's starting XI."""
    starting = {p[0] for p in lineup.players}
    return [r for r in regulars(conn, team, before_iso, **kw) if r["id"] not in starting]
