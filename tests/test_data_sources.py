import httpx
import respx
from kalshi_edge.data.sources import download_text


@respx.mock
def test_download_text_returns_body():
    respx.get("https://example.test/x.csv").mock(
        return_value=httpx.Response(200, text="a,b\n1,2\n"))
    assert download_text("https://example.test/x.csv") == "a,b\n1,2\n"


@respx.mock
def test_download_text_raises_on_error():
    respx.get("https://example.test/x.csv").mock(return_value=httpx.Response(404))
    try:
        download_text("https://example.test/x.csv")
        assert False, "expected HTTPStatusError"
    except httpx.HTTPStatusError:
        pass
