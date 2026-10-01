from collections.abc import Iterator
from kalshi_edge.kalshi.http import KalshiHTTP
from kalshi_edge.kalshi.models import Orderbook
from kalshi_edge.kalshi.orderbook import parse_orderbook


class KalshiClient:
    """Read-only. Contains no order-placement methods by design."""

    def __init__(self, http: KalshiHTTP):
        self._http = http

    def iter_markets(self, *, status="open", series_ticker=None,
                     event_ticker=None, limit=100) -> Iterator[dict]:
        cursor = None
        while True:
            params = {"limit": limit, "status": status}
            if series_ticker:
                params["series_ticker"] = series_ticker
            if event_ticker:
                params["event_ticker"] = event_ticker
            if cursor:
                params["cursor"] = cursor
            body = self._http.get_json("/markets", params=params)
            yield from body.get("markets", [])
            cursor = body.get("cursor") or ""
            if not cursor:
                return

    def get_market(self, ticker: str) -> dict:
        return self._http.get_json(f"/markets/{ticker}")["market"]

    def get_orderbook(self, ticker: str) -> Orderbook:
        body = self._http.get_json(f"/markets/{ticker}/orderbook")
        # Live API wraps the book in `orderbook_fp` (dollar strings); older shape used
        # `orderbook` (cents). parse_orderbook normalizes either representation.
        raw = body.get("orderbook_fp") or body.get("orderbook") or {}
        return parse_orderbook(raw, ticker=ticker)

    def get_events(self, *, series_ticker=None, status="open") -> list[dict]:
        params = {"status": status}
        if series_ticker:
            params["series_ticker"] = series_ticker
        return self._http.get_json("/events", params=params).get("events", [])

    def get_series(self, series_ticker: str) -> dict:
        return self._http.get_json(f"/series/{series_ticker}")["series"]

    def get_historical_market(self, ticker: str) -> dict:
        body = self._http.get_json(f"/historical/markets/{ticker}")
        return body.get("market", body)

    def get_historical_markets(self, *, series_ticker=None, limit=100) -> list[dict]:
        params = {"limit": limit}
        if series_ticker:
            params["series_ticker"] = series_ticker
        return self._http.get_json("/historical/markets", params=params).get("markets", [])

    def get_historical_candlesticks(self, ticker, *, start_ts, end_ts,
                                    period_interval) -> list[dict]:
        params = {"start_ts": start_ts, "end_ts": end_ts, "period_interval": period_interval}
        body = self._http.get_json(f"/historical/markets/{ticker}/candlesticks", params=params)
        return body.get("candlesticks", [])

    def iter_historical_markets(self, *, series_ticker=None, limit=1000) -> Iterator[dict]:
        """All archived markets for a series, following the cursor."""
        cursor = ""
        while True:
            params = {"limit": limit}
            if series_ticker:
                params["series_ticker"] = series_ticker
            if cursor:
                params["cursor"] = cursor
            body = self._http.get_json("/historical/markets", params=params)
            yield from body.get("markets", [])
            cursor = body.get("cursor") or ""
            if not cursor:
                return
