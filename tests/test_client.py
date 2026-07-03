import httpx
import respx
from kalshi_edge.kalshi.client import KalshiClient

BASE = "https://api.example.test/trade-api/v2"


def _client() -> KalshiClient:
    from kalshi_edge.kalshi.http import KalshiHTTP
    return KalshiClient(http=KalshiHTTP(base_url=BASE, backoff=0))


@respx.mock
def test_iter_markets_follows_cursor():
    respx.get(f"{BASE}/markets").mock(side_effect=[
        httpx.Response(200, json={"markets": [{"ticker": "A"}], "cursor": "c1"}),
        httpx.Response(200, json={"markets": [{"ticker": "B"}], "cursor": ""}),
    ])
    tickers = [m["ticker"] for m in _client().iter_markets(series_ticker="S")]
    assert tickers == ["A", "B"]


@respx.mock
def test_get_orderbook_returns_parsed_orderbook():
    respx.get(f"{BASE}/markets/T/orderbook").mock(return_value=httpx.Response(
        200, json={"orderbook": {"yes": [[60, 100]], "no": [[38, 200]]}}))
    ob = _client().get_orderbook("T")
    assert ob.ticker == "T" and ob.yes[0].price == 60 and ob.no[0].price == 38


@respx.mock
def test_get_market_returns_market_dict():
    respx.get(f"{BASE}/markets/T").mock(return_value=httpx.Response(
        200, json={"market": {"ticker": "T", "title": "X"}}))
    assert _client().get_market("T")["title"] == "X"


@respx.mock
def test_historical_candlesticks_passes_params():
    route = respx.get(f"{BASE}/historical/markets/T/candlesticks").mock(
        return_value=httpx.Response(200, json={"candlesticks": []}))
    _client().get_historical_candlesticks("T", start_ts=1, end_ts=2, period_interval=60)
    assert route.calls.last.request.url.params["period_interval"] == "60"


from scripts.pull_today import format_market_line
from kalshi_edge.kalshi.models import EffectivePrices


def test_format_market_line_renders_prices():
    ep = EffectivePrices(yes_bid=0.60, yes_ask=0.62, yes_mid=0.61, spread=0.02)
    line = format_market_line({"ticker": "T", "title": "Brazil win"}, ep)
    assert "T" in line and "Brazil win" in line and "0.60" in line and "0.62" in line


def test_format_market_line_handles_missing_prices():
    ep = EffectivePrices(yes_bid=None, yes_ask=None, yes_mid=None, spread=None)
    line = format_market_line({"ticker": "T", "title": "X"}, ep)
    assert "n/a" in line
