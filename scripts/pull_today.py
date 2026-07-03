from datetime import date, timezone, datetime
from kalshi_edge.config import KALSHI_BASE_URL, SOCCER_SERIES_TICKERS
from kalshi_edge.kalshi.http import KalshiHTTP
from kalshi_edge.kalshi.client import KalshiClient
from kalshi_edge.kalshi.soccer import todays_soccer_markets
from kalshi_edge.kalshi.orderbook import effective_prices
from kalshi_edge.kalshi.models import EffectivePrices


def _fmt(v: float | None) -> str:
    return f"{v:.2f}" if v is not None else "n/a"


def format_market_line(market: dict, ep: EffectivePrices) -> str:
    return (f"{market.get('ticker'):<28} {market.get('title', ''):<40} "
            f"bid={_fmt(ep.yes_bid)} ask={_fmt(ep.yes_ask)} "
            f"mid={_fmt(ep.yes_mid)} spr={_fmt(ep.spread)}")


def main() -> None:
    client = KalshiClient(http=KalshiHTTP(base_url=KALSHI_BASE_URL))
    today = datetime.now(timezone.utc).date()
    if not SOCCER_SERIES_TICKERS:
        print("No SOCCER_SERIES_TICKERS configured — run scripts/record_fixtures.py first.")
        return
    for market in todays_soccer_markets(client, SOCCER_SERIES_TICKERS, today):
        ob = client.get_orderbook(market["ticker"])
        print(format_market_line(market, effective_prices(ob)))


if __name__ == "__main__":
    main()
