"""API-Football lineups: fetch, parse, and match to our fixtures.

Budget (free plan, 100 req/day): one ``/fixtures?date=`` call per day (cached) plus one
``/fixtures/lineups`` call per game. Lineups are published ~60 min before kickoff; an empty
response is *not* cached so a later run can pick the real one up.
"""
from dataclasses import dataclass
from datetime import date, datetime, timezone

from kalshi_edge.kalshi.club_match import name_score


@dataclass(frozen=True)
class Lineup:
    team_id: int
    team: str                                  # API-Football spelling
    formation: str | None
    players: tuple[tuple[int, str, str], ...]  # (player_id, name, pos G/D/M/F) of the starting XI


def parse_lineups(resp: list) -> dict[int, Lineup]:
    """``/fixtures/lineups`` response -> {team_id: Lineup}. Entries with no XI are dropped."""
    out = {}
    for entry in resp or []:
        xi = [(p["player"].get("id"), p["player"].get("name") or "", p["player"].get("pos") or "")
              for p in entry.get("startXI") or [] if p.get("player")]
        team = entry.get("team") or {}
        if len(xi) >= 11 and team.get("id") is not None:
            out[team["id"]] = Lineup(team["id"], team.get("name") or "", entry.get("formation"), tuple(xi))
    return out


def fixtures_for_day(api, day: date) -> list:
    return api.get("/fixtures", {"date": day.isoformat()})


def find_fixture(fixtures: list, home: str, away: str, kickoff: datetime,
                 tol_seconds: int = 3 * 3600, min_score: float = 0.6):
    """Best API fixture for our (home, away) at ``kickoff`` by fuzzy team-name match, or None."""
    best, best_score = None, 0.0
    for f in fixtures:
        ts = (f.get("fixture") or {}).get("timestamp")
        if ts is None or abs(ts - kickoff.timestamp()) > tol_seconds:
            continue
        teams = f.get("teams") or {}
        score = min(name_score(home, (teams.get("home") or {}).get("name", "")),
                    name_score(away, (teams.get("away") or {}).get("name", "")))
        if score >= min_score and score > best_score:
            best, best_score = f, score
    return best


def fetch_match_lineups(api, fixture: dict) -> tuple[Lineup, Lineup] | None:
    """-> (home_lineup, away_lineup) once published, else None."""
    teams = fixture["teams"]
    by_team = parse_lineups(api.get("/fixtures/lineups", {"fixture": str(fixture["fixture"]["id"])},
                                    cache_empty=False))
    home, away = by_team.get(teams["home"]["id"]), by_team.get(teams["away"]["id"])
    return (home, away) if home and away else None


def iso(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()
