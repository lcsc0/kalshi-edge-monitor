import pytest
from kalshi_edge.config import KALSHI_BASE_URL
from kalshi_edge.kalshi.http import KalshiHTTP
from kalshi_edge.kalshi.client import KalshiClient


@pytest.mark.live
def test_live_markets_endpoint_returns_markets():
    client = KalshiClient(http=KalshiHTTP(base_url=KALSHI_BASE_URL))
    markets = list_first(client.iter_markets(status="open", limit=5))
    assert markets, "expected at least one open market from the live API"
    assert "ticker" in markets[0]


def list_first(it, n=5):
    out = []
    for i, x in enumerate(it):
        out.append(x)
        if i + 1 >= n:
            break
    return out
