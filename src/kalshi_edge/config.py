# Public market-data base. Verified live against the Kalshi API (2026-07-03).
# Override via KalshiHTTP(base_url=...) if the host differs.
KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

# Per-match World Cup soccer series to scan for today's games. Discovered live via
# scripts/record_fixtures.py on 2026-07-03. Tournament / advancement / futures series
# (e.g. KXWCADVANCE, KXWCSTAGE, group/host/winner) are deliberately excluded.
SOCCER_SERIES_TICKERS: list[str] = [
    "KXWCGAME",         # match moneyline / game
    "KXWCTOTAL",        # match total goals
    "KXWCTOTALGOAL",    # total goals (alt)
    "KXWCSPREAD",       # match spread
    "KXWCBTTS",         # both teams to score
    "KXWCTEAMTOTAL",    # team total goals
    "KXWCSCORE",        # correct score
    "KXWCPLAYERGOALS",  # player goals (key-striker props)
    "KXWCMATCHUP",      # matchup
    "KXWCTEAMH2H",      # team head-to-head
]

# Club league series prefix (Kalshi: KX<prefix>GAME / TOTAL / BTTS / SPREAD) ->
# football-data.co.uk tournament label stored in data/clubs.sqlite.
CLUB_LEAGUES: dict[str, str] = {
    "EPL": "EPL",
    "EFLCHAMPIONSHIP": "EFL Championship",
    "BUNDESLIGA": "Bundesliga",
    "SERIEA": "Serie A",
    "LALIGA": "La Liga",
    "LIGUE1": "Ligue 1",
    "EREDIVISIE": "Eredivisie",
    "LIGAPORTUGAL": "Liga Portugal",
}
CLUB_MARKET_KINDS = ("GAME", "TOTAL", "BTTS", "SPREAD")

import os
from pathlib import Path


def load_env(path: str = ".env") -> None:
    """Load KEY=VALUE lines from a .env file into os.environ (no overwrite)."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())


def anthropic_api_key() -> str:
    """Anthropic API key for LLM steps: ``ANTHROPIC_API_KEY``, else ``KALSHI_ANTHROPIC_KEY``.
    Returns "" if neither is set. Never log the value."""
    return os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("KALSHI_ANTHROPIC_KEY", "")
