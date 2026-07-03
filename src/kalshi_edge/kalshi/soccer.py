from datetime import date, datetime
from collections.abc import Iterator
from kalshi_edge.kalshi.client import KalshiClient

# Kalshi's `close_time` is a late settlement backstop (often weeks after kickoff),
# NOT the match time. The real game datetime is `occurrence_datetime`, with
# `expected_expiration_time` as a fallback.
_GAME_TIME_FIELDS = ("occurrence_datetime", "expected_expiration_time")


def market_game_date(market: dict) -> date | None:
    """Return the date the match actually occurs, or None if unknown."""
    for field in _GAME_TIME_FIELDS:
        ts = market.get(field)
        if ts:
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).date()
    return None


def filter_markets_on_game_date(markets: list[dict], target: date) -> list[dict]:
    return [m for m in markets if market_game_date(m) == target]


def todays_soccer_markets(client: KalshiClient, series_tickers: list[str],
                          target: date) -> Iterator[dict]:
    """Yield open markets in the given soccer series whose match occurs on `target`."""
    for series in series_tickers:
        markets = list(client.iter_markets(series_ticker=series, status="open"))
        yield from filter_markets_on_game_date(markets, target)
