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
