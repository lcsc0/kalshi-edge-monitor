import csv
import io
from datetime import datetime, timezone

RESULTS_URL = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
GOALS_URL = "https://raw.githubusercontent.com/martj42/international_results/master/goalscorers.csv"


def _flag(v) -> int:
    return 1 if str(v).strip().upper() == "TRUE" else 0


def _int(v):
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def _record(conn, source: str, n: int) -> None:
    conn.execute("INSERT OR REPLACE INTO source_meta VALUES (?,?,?)",
                 (source, datetime.now(timezone.utc).isoformat(), n))


def load_results_csv(conn, text: str) -> int:
    rows = list(csv.DictReader(io.StringIO(text)))
    conn.executemany(
        "INSERT INTO matches VALUES (?,?,?,?,?,?,?,?,?)",
        [(r["date"], r["home_team"], r["away_team"],
          _int(r["home_score"]), _int(r["away_score"]),
          r["tournament"], r["city"], r["country"], _flag(r["neutral"])) for r in rows])
    _record(conn, "results", len(rows))
    conn.commit()
    return len(rows)


def team_matches(conn, team: str, since: str | None = None) -> list[dict]:
    query = "SELECT * FROM matches WHERE (home_team = ? OR away_team = ?)"
    args = [team, team]
    if since:
        query += " AND date >= ?"
        args.append(since)
    query += " ORDER BY date"
    return [dict(r) for r in conn.execute(query, args).fetchall()]


def team_goal_rates(conn, team: str, since: str | None = None) -> tuple[float, float]:
    """Average goals scored and conceded per completed match."""
    matches = [m for m in team_matches(conn, team, since)
               if m["home_score"] is not None and m["away_score"] is not None]
    if not matches:
        return (0.0, 0.0)
    scored = conceded = 0
    for m in matches:
        if m["home_team"] == team:
            scored += m["home_score"]; conceded += m["away_score"]
        else:
            scored += m["away_score"]; conceded += m["home_score"]
    n = len(matches)
    return (scored / n, conceded / n)


def load_goalscorers_csv(conn, text: str) -> int:
    rows = list(csv.DictReader(io.StringIO(text)))
    conn.executemany(
        "INSERT INTO goals VALUES (?,?,?,?,?,?,?,?)",
        [(r["date"], r["home_team"], r["away_team"], r["team"], r["scorer"],
          _int(r["minute"]), _flag(r["own_goal"]), _flag(r["penalty"])) for r in rows])
    _record(conn, "goalscorers", len(rows))
    conn.commit()
    return len(rows)


def player_goal_count(conn, scorer: str, since: str | None = None) -> int:
    query = "SELECT COUNT(*) FROM goals WHERE scorer = ? AND own_goal = 0"
    args = [scorer]
    if since:
        query += " AND date >= ?"
        args.append(since)
    return conn.execute(query, args).fetchone()[0]
