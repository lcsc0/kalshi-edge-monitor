"""GET-only Kalshi HTTP with call spacing and 429 handling (Retry-After honoured)."""
import threading
import time

import httpx

from kalshi_edge.kalshi.http import KalshiHTTP


class ThrottledHTTP(KalshiHTTP):
    def __init__(self, *a, min_gap: float = 0.15, max_429: int = 4, **kw):
        super().__init__(*a, **kw)
        self.min_gap, self.max_429 = min_gap, max_429
        self._lock, self._last = threading.Lock(), 0.0
        self.n_429 = 0

    def _wait(self):
        with self._lock:
            now = time.monotonic()
            nxt = max(now, self._last + self.min_gap)
            self._last = nxt
        if nxt > now:
            time.sleep(nxt - now)

    def get_json(self, path, params=None):
        url = f"{self.base_url}{path}"
        last = None
        for attempt in range(self.max_429 + 1):
            self._wait()
            try:
                resp = self._client.get(url, params=params)
            except httpx.TransportError as e:
                last = e
                time.sleep(0.5 * (attempt + 1))
                continue
            if resp.status_code == 429:
                self.n_429 += 1
                try:
                    delay = float(resp.headers.get("retry-after", ""))
                except ValueError:
                    delay = 1.0 * (2 ** attempt)
                last = httpx.HTTPStatusError("429", request=resp.request, response=resp)
                time.sleep(min(delay, 15.0))
                continue
            resp.raise_for_status()
            return resp.json()
        raise last
