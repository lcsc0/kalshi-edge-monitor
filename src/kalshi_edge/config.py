# Public market-data base. Verify against docs.kalshi.com in Task 10's live smoke test;
# override via KalshiHTTP(base_url=...) if the host differs.
KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

# Soccer series tickers to scan. Seed from the live API in Task 10 (record_fixtures),
# then paste the real tickers here.
SOCCER_SERIES_TICKERS: list[str] = []
