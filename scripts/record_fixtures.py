import json
from pathlib import Path
from kalshi_edge.config import KALSHI_BASE_URL
from kalshi_edge.kalshi.http import KalshiHTTP

OUT = Path("tests/fixtures")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    http = KalshiHTTP(base_url=KALSHI_BASE_URL)
    # 1) find soccer series
    series = http.get_json("/series", params={"category": "Sports"})
    (OUT / "series_sports.json").write_text(json.dumps(series, indent=2))
    # 2) grab a page of open markets + one orderbook to confirm response shape
    markets = http.get_json("/markets", params={"status": "open", "limit": 20})
    (OUT / "markets_open.json").write_text(json.dumps(markets, indent=2))
    ticker = markets["markets"][0]["ticker"]
    ob = http.get_json(f"/markets/{ticker}/orderbook")
    (OUT / "orderbook_sample.json").write_text(json.dumps(ob, indent=2))
    print(f"Wrote fixtures to {OUT}. Inspect series_sports.json for soccer/World Cup "
          f"series tickers and paste them into config.SOCCER_SERIES_TICKERS.")


if __name__ == "__main__":
    main()
