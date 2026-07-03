from datetime import date, datetime
from collections.abc import Iterator
from kalshi_edge.kalshi.client import KalshiClient


def filter_markets_closing_on(markets: list[dict], target: date) -> list[dict]:
    out = []
    for m in markets:
        ct = m.get("close_time")
        if not ct:
            continue
        closes = datetime.fromisoformat(ct.replace("Z", "+00:00")).date()
        if closes == target:
            out.append(m)
    return out


def todays_soccer_markets(client: KalshiClient, series_tickers: list[str],
                          target: date) -> Iterator[dict]:
    """Yield open markets in the given soccer series that close on `target`."""
    for series in series_tickers:
        markets = list(client.iter_markets(series_ticker=series, status="open"))
        yield from filter_markets_closing_on(markets, target)
