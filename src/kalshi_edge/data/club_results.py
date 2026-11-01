"""Club results + fixtures from football-data.co.uk (top European leagues).

``load_club_csv`` loads played matches (and their kickoff times) from a season CSV;
``load_fixtures_csv`` loads upcoming fixtures from ``fixtures.csv`` into the same
tables with NULL scores. Kickoff times in these files are UK local time, stored as
UTC epoch seconds in the ``kickoffs`` table.
"""
import csv
import io
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

BASE_URL = "https://www.football-data.co.uk/mmz4281/{season}/{div}.csv"
FIXTURES_URL = "https://www.football-data.co.uk/fixtures.csv"

# football-data division code -> tournament label (matches kalshi_edge.config.CLUB_LEAGUES values)
LEAGUES: dict[str, str] = {
    "E0": "EPL",
    "E1": "EFL Championship",
    "D1": "Bundesliga",
    "I1": "Serie A",
    "SP1": "La Liga",
    "F1": "Ligue 1",
    "N1": "Eredivisie",
    "P1": "Liga Portugal",
}

_UK = ZoneInfo("Europe/London")
_KICKOFFS = ("CREATE TABLE IF NOT EXISTS kickoffs "
             "(date TEXT, home_team TEXT, away_team TEXT, kickoff_utc INTEGER)")


def season_codes(first: int, last: int) -> list[str]:
    """Season start years -> football-data codes: (2019, 2021) -> ['1920', '2021', '2122']."""
    return [f"{y % 100:02d}{(y + 1) % 100:02d}" for y in range(first, last + 1)]


def _parse_date(s: str):
    s = (s or "").strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _int(v):
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def _kickoff_utc(day, time_s: str):
    time_s = (time_s or "").strip()
    if not time_s:
        return None
    try:
        hh, mm = (int(x) for x in time_s.split(":")[:2])
    except ValueError:
        return None
    local = datetime(day.year, day.month, day.day, hh, mm, tzinfo=_UK)
    return int(local.astimezone(timezone.utc).timestamp())


def _load(conn, text: str, div: str | None, played_only: bool) -> int:
    conn.execute(_KICKOFFS)
    n = 0
    for r in csv.DictReader(io.StringIO(text.lstrip("﻿"))):
        code = div or (r.get("Div") or "").strip()
        tournament = LEAGUES.get(code)
        day = _parse_date(r.get("Date"))
        home, away = (r.get("HomeTeam") or "").strip(), (r.get("AwayTeam") or "").strip()
        if tournament is None or day is None or not home or not away:
            continue
        hs, as_ = _int(r.get("FTHG")), _int(r.get("FTAG"))
        if played_only and (hs is None or as_ is None):
            continue
        d = day.isoformat()
        conn.execute("INSERT INTO matches VALUES (?,?,?,?,?,?,?,?,?)",
                     (d, home, away, hs, as_, tournament, "", "", 0))
        ko = _kickoff_utc(day, r.get("Time"))
        if ko is not None:
            conn.execute("INSERT INTO kickoffs VALUES (?,?,?,?)", (d, home, away, ko))
        n += 1
    conn.commit()
    return n


def load_club_csv(conn, text: str, div: str) -> int:
    """Load played matches of one division's season CSV; returns rows loaded."""
    return _load(conn, text, div, played_only=True)


def load_fixtures_csv(conn, text: str) -> int:
    """Load upcoming fixtures (any division in ``LEAGUES``) with NULL scores."""
    return _load(conn, text, None, played_only=False)
