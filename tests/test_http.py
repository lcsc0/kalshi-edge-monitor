import httpx
import respx
from kalshi_edge.kalshi.http import KalshiHTTP

BASE = "https://api.example.test/trade-api/v2"


@respx.mock
def test_get_json_returns_body():
    respx.get(f"{BASE}/markets").mock(return_value=httpx.Response(200, json={"markets": []}))
    http = KalshiHTTP(base_url=BASE, backoff=0)
    assert http.get_json("/markets") == {"markets": []}


@respx.mock
def test_get_json_retries_on_500_then_succeeds():
    route = respx.get(f"{BASE}/markets").mock(
        side_effect=[httpx.Response(500), httpx.Response(200, json={"ok": True})]
    )
    http = KalshiHTTP(base_url=BASE, backoff=0)
    assert http.get_json("/markets") == {"ok": True}
    assert route.call_count == 2


@respx.mock
def test_get_json_raises_after_max_retries():
    respx.get(f"{BASE}/markets").mock(return_value=httpx.Response(503))
    http = KalshiHTTP(base_url=BASE, max_retries=2, backoff=0)
    try:
        http.get_json("/markets")
        assert False, "expected HTTPStatusError"
    except httpx.HTTPStatusError as exc:
        assert exc.response.status_code == 503
