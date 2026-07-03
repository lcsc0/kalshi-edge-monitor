import time
import httpx


class KalshiHTTP:
    def __init__(self, base_url, timeout=10.0, max_retries=3, backoff=0.5, client=None):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self._client = client or httpx.Client(timeout=timeout)

    def get_json(self, path: str, params: dict | None = None) -> dict:
        url = f"{self.base_url}{path}"
        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                resp = self._client.get(url, params=params)
                if resp.status_code >= 500:
                    resp.raise_for_status()
                resp.raise_for_status()
                return resp.json()
            except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                last_exc = exc
                if attempt < self.max_retries - 1:
                    time.sleep(self.backoff * (2 ** attempt))
        raise last_exc
