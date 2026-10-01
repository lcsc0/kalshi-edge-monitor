import httpx
import respx
from kalshi_edge.data.cache import connect
from kalshi_edge.enrich.apifootball import ApiFootball

BASE = "https://v3.football.api-sports.io"


def _api(conn):
    return ApiFootball(api_key="testkey", conn=conn,
                       http=httpx.Client(base_url=BASE))


@respx.mock
def test_get_returns_response_list_and_sends_key_header():
    route = respx.get(f"{BASE}/teams").mock(return_value=httpx.Response(
        200, json={"results": 1, "errors": [], "response": [{"team": {"id": 27, "name": "Portugal"}}]}))
    conn = connect()
    out = _api(conn).get("/teams", {"search": "portugal"})
    assert out == [{"team": {"id": 27, "name": "Portugal"}}]
    assert route.calls.last.request.headers["x-apisports-key"] == "testkey"


@respx.mock
def test_second_identical_call_is_served_from_cache():
    route = respx.get(f"{BASE}/coachs").mock(return_value=httpx.Response(
        200, json={"results": 1, "errors": [], "response": [{"name": "Coach"}]}))
    conn = connect(); api = _api(conn)
    api.get("/coachs", {"team": "27"})
    api.get("/coachs", {"team": "27"})
    assert route.call_count == 1


@respx.mock
def test_api_errors_envelope_raises():
    respx.get(f"{BASE}/teams").mock(return_value=httpx.Response(
        200, json={"results": 0, "errors": {"token": "invalid"}, "response": []}))
    conn = connect()
    try:
        _api(conn).get("/teams", {"search": "x"})
        assert False, "expected RuntimeError on errors envelope"
    except RuntimeError as exc:
        assert "invalid" in str(exc)
