"""Live scores from ESPN's public scoreboard (no key; ``cache-control: max-age=1``)."""
import re
from dataclasses import dataclass

import httpx

# ESPN league slug -> Kalshi series prefix (KX<prefix>GAME ...), see config.CLUB_LEAGUES.
ESPN_LEAGUES = {
    "eng.1": "EPL", "eng.2": "EFLCHAMPIONSHIP", "ger.1": "BUNDESLIGA", "ita.1": "SERIEA",
    "esp.1": "LALIGA", "fra.1": "LIGUE1", "ned.1": "EREDIVISIE", "por.1": "LIGAPORTUGAL",
}
URL = "https://site.api.espn.com/apis/site/v2/sports/soccer/{slug}/scoreboard"
_CLOCK = re.compile(r"(\d+)'(?:\s*\+\s*(\d+)')?")


@dataclass(frozen=True)
class LiveGame:
    game_id: str
    slug: str
    home: str
    away: str
    home_score: int
    away_score: int
    state: str          # "pre" | "in" | "post"
    status_name: str    # e.g. STATUS_FIRST_HALF, STATUS_HALFTIME
    period: int
    minute: float       # match minute incl. stoppage ("45'+3'" -> 48)
    red_home: int
    red_away: int
    kickoff: str


def parse_minute(display_clock: str, clock_seconds: float = 0.0) -> float:
    m = _CLOCK.search(display_clock or "")
    if m:
        return float(m.group(1)) + float(m.group(2) or 0)
    return float(clock_seconds or 0) / 60.0


def parse_event(slug: str, ev: dict) -> LiveGame | None:
    comp = ev["competitions"][0]
    by = {c["homeAway"]: c for c in comp["competitors"]}
    if "home" not in by or "away" not in by:
        return None
    st = ev["status"]
    team_side = {c["team"]["id"]: c["homeAway"] for c in comp["competitors"]}
    reds = {"home": 0, "away": 0}
    for d in comp.get("details", []):
        if d.get("redCard"):
            side = team_side.get((d.get("team") or {}).get("id"))
            if side:
                reds[side] += 1
    return LiveGame(
        game_id=str(ev["id"]), slug=slug,
        home=by["home"]["team"]["displayName"], away=by["away"]["team"]["displayName"],
        home_score=int(by["home"].get("score") or 0), away_score=int(by["away"].get("score") or 0),
        state=st["type"]["state"], status_name=st["type"]["name"], period=int(st.get("period") or 0),
        minute=parse_minute(st.get("displayClock", ""), st.get("clock", 0)),
        red_home=reds["home"], red_away=reds["away"], kickoff=ev.get("date", ""))


def fetch_league(slug: str, client: httpx.Client | None = None, timeout: float = 10.0) -> list[LiveGame]:
    c = client or httpx
    body = c.get(URL.format(slug=slug), timeout=timeout).raise_for_status().json()
    out = []
    for ev in body.get("events", []):
        g = parse_event(slug, ev)
        if g is not None:
            out.append(g)
    return out
