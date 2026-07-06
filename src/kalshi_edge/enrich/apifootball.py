import json
import os
from datetime import datetime, timezone
import httpx

BASE_URL = "https://v3.football.api-sports.io"


class ApiFootball:
    """Read-only API-Football client. Caches every response in SQLite to respect the
    100/day free limit. Never logs the key."""

    def __init__(self, api_key: str | None = None, conn=None, http: httpx.Client | None = None):
        self.api_key = api_key or os.environ.get("API_FOOTBALL_KEY", "")
        self.conn = conn
        self._http = http or httpx.Client(base_url=BASE_URL, timeout=20.0)
        if conn is not None:
            conn.execute("CREATE TABLE IF NOT EXISTS api_cache "
                         "(key TEXT PRIMARY KEY, json TEXT, fetched_at TEXT)")

    def _cache_key(self, path: str, params: dict) -> str:
        return path + "?" + "&".join(f"{k}={params[k]}" for k in sorted(params))

    def get(self, path: str, params: dict | None = None) -> list:
        params = params or {}
        ck = self._cache_key(path, params)
        if self.conn is not None:
            row = self.conn.execute("SELECT json FROM api_cache WHERE key = ?", (ck,)).fetchone()
            if row is not None:
                return json.loads(row[0])
        resp = self._http.get(path, params=params, headers={"x-apisports-key": self.api_key})
        resp.raise_for_status()
        body = resp.json()
        errors = body.get("errors")
        if errors:
            raise RuntimeError(f"API-Football error: {errors}")
        data = body.get("response", [])
        if self.conn is not None:
            self.conn.execute(
                "INSERT OR REPLACE INTO api_cache VALUES (?,?,?)",
                (ck, json.dumps(data), datetime.now(timezone.utc).isoformat()))
            self.conn.commit()
        return data
