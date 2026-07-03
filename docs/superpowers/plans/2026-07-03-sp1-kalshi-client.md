# SP1 — Kalshi Read-Only Client + Market Puller — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A read-only Python client for Kalshi that enumerates today's soccer markets and reconstructs effective bid/ask/mid/depth (incl. slippage for a target size) from the yes-bid/no-bid orderbook, plus historical-data access for the later backtest.

**Architecture:** Pure, network-free orderbook math (`orderbook.py`) is the tested core. A thin retrying HTTP wrapper (`http.py`) and a `KalshiClient` (`client.py`) provide market/orderbook/historical access, mocked in tests with `respx`. A `soccer.py` helper filters today's markets, and a `pull_today` CLI prints effective prices. No order endpoints exist anywhere in this package.

**Tech Stack:** Python 3.11+, httpx, respx (test), pytest. No auth needed — Kalshi market-data endpoints are public.

---

## File Structure

```
pyproject.toml
src/kalshi_edge/
  __init__.py
  config.py              # base URL, timeouts, configured soccer series tickers
  kalshi/
    __init__.py
    models.py            # OrderbookLevel, Orderbook, EffectivePrices, Fill dataclasses
    orderbook.py         # PURE: parse_orderbook, effective_prices, simulate_buy_yes/no
    http.py              # KalshiHTTP: get_json with retry/backoff
    client.py            # KalshiClient: markets/orderbook/events/series/historical
    soccer.py            # todays_soccer_markets(client, series, now)
scripts/
  pull_today.py          # CLI: print today's soccer markets + effective prices
  record_fixtures.py     # one-off: save real API JSON into tests/fixtures
tests/
  test_orderbook.py      # pure-function tests (no network) — the core
  test_http.py           # retry via respx
  test_client.py         # client wiring + pagination via respx
  test_soccer.py         # today filter
  test_live_smoke.py     # marked 'live', skipped by default; hits real API
```

**Key domain facts (get these right):**
- Kalshi binary market has a YES and NO side. The orderbook returns **resting bids only** on each side (no asks).
- A **NO bid at price `q` cents** is economically an **offer to sell YES at `100 - q`**. So:
  - `effective yes bid = best (highest) YES bid`
  - `effective yes ask = 100 - best (highest) NO bid`
- Prices are cents (1–99); divide by 100 for probability. Some responses use dollar-strings (`"0.60"`) with `_dollars`/`_fp` keys — the parser normalizes both.
- To **buy YES** you consume the NO-bid book from best (highest NO price = lowest YES ask) downward; VWAP over consumed levels gives the fill price, and the gap vs top-of-book is slippage. Buying NO is symmetric over the YES-bid book.

---

## Task 1: Project scaffold

**Files:**
- Create: `pyproject.toml`
- Create: `src/kalshi_edge/__init__.py`
- Create: `src/kalshi_edge/kalshi/__init__.py`
- Test: `tests/test_smoke.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_smoke.py
import kalshi_edge


def test_package_imports_and_has_version():
    assert kalshi_edge.__version__ == "0.1.0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_smoke.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kalshi_edge'`

- [ ] **Step 3: Create pyproject and package files**

```toml
# pyproject.toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "kalshi-edge-monitor"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = ["httpx>=0.27"]

[project.optional-dependencies]
dev = ["pytest>=8", "respx>=0.21"]

[tool.hatch.build.targets.wheel]
packages = ["src/kalshi_edge"]

[tool.pytest.ini_options]
pythonpath = ["src"]
markers = ["live: hits the real Kalshi API (skipped unless --run-live)"]
```

```python
# src/kalshi_edge/__init__.py
__version__ = "0.1.0"
```

```python
# src/kalshi_edge/kalshi/__init__.py
```

- [ ] **Step 4: Install dev deps and run the test**

Run: `python -m pip install -e ".[dev]" && python -m pytest tests/test_smoke.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/kalshi_edge tests/test_smoke.py
git commit -m "chore: scaffold kalshi_edge package"
```

---

## Task 2: Orderbook data models

**Files:**
- Create: `src/kalshi_edge/kalshi/models.py`
- Test: `tests/test_orderbook.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_orderbook.py
from kalshi_edge.kalshi.models import OrderbookLevel, Orderbook, EffectivePrices, Fill


def test_models_construct():
    lvl = OrderbookLevel(price=60, count=100)
    ob = Orderbook(ticker="T", yes=(lvl,), no=())
    ep = EffectivePrices(yes_bid=0.60, yes_ask=None, yes_mid=None, spread=None)
    fill = Fill(filled=0, avg_price=None, slippage=None)
    assert lvl.price == 60 and ob.ticker == "T" and ep.yes_bid == 0.60 and fill.filled == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_orderbook.py::test_models_construct -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kalshi_edge.kalshi.models'`

- [ ] **Step 3: Write the models**

```python
# src/kalshi_edge/kalshi/models.py
from dataclasses import dataclass


@dataclass(frozen=True)
class OrderbookLevel:
    price: int   # cents, 1..99
    count: int   # number of contracts resting at this price


@dataclass(frozen=True)
class Orderbook:
    ticker: str
    yes: tuple[OrderbookLevel, ...]  # resting YES bids, best (highest price) first
    no: tuple[OrderbookLevel, ...]   # resting NO bids, best (highest price) first


@dataclass(frozen=True)
class EffectivePrices:
    yes_bid: float | None   # probability 0..1
    yes_ask: float | None
    yes_mid: float | None
    spread: float | None


@dataclass(frozen=True)
class Fill:
    filled: int             # contracts actually fillable
    avg_price: float | None # VWAP as probability 0..1
    slippage: float | None  # avg_price - best-of-book price
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_orderbook.py::test_models_construct -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/kalshi_edge/kalshi/models.py tests/test_orderbook.py
git commit -m "feat: add orderbook data models"
```

---

## Task 3: Parse + normalize raw orderbook

**Files:**
- Create: `src/kalshi_edge/kalshi/orderbook.py`
- Test: `tests/test_orderbook.py` (append)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_orderbook.py (append)
from kalshi_edge.kalshi.orderbook import parse_orderbook


def test_parse_cents_int_shape_sorts_best_first():
    raw = {"yes": [[59, 50], [60, 100]], "no": [[37, 100], [38, 200]]}
    ob = parse_orderbook(raw, ticker="T")
    assert ob.yes[0].price == 60 and ob.yes[0].count == 100
    assert ob.yes[1].price == 59
    assert ob.no[0].price == 38 and ob.no[0].count == 200


def test_parse_dollar_string_shape_normalizes_to_cents():
    raw = {"yes_dollars": [["0.60", "100"]], "no_dollars": [["0.38", "200"]]}
    ob = parse_orderbook(raw, ticker="T")
    assert ob.yes[0].price == 60 and ob.yes[0].count == 100
    assert ob.no[0].price == 38 and ob.no[0].count == 200


def test_parse_empty_sides():
    ob = parse_orderbook({"yes": None, "no": []}, ticker="T")
    assert ob.yes == () and ob.no == ()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_orderbook.py -k parse -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kalshi_edge.kalshi.orderbook'`

- [ ] **Step 3: Write parse_orderbook**

```python
# src/kalshi_edge/kalshi/orderbook.py
from kalshi_edge.kalshi.models import OrderbookLevel, Orderbook, EffectivePrices, Fill


def _to_cents(price) -> int:
    """Accept int cents (60) or dollar string/float ('0.60', 0.6) -> int cents."""
    if isinstance(price, str):
        price = float(price)
    if isinstance(price, float):
        return round(price * 100) if price <= 1.0 else round(price)
    return int(price)


def _to_count(count) -> int:
    return int(float(count)) if isinstance(count, str) else int(count)


def _levels(rows) -> tuple[OrderbookLevel, ...]:
    if not rows:
        return ()
    levels = [OrderbookLevel(price=_to_cents(p), count=_to_count(c)) for p, c in rows]
    return tuple(sorted(levels, key=lambda lvl: lvl.price, reverse=True))


def parse_orderbook(raw: dict, ticker: str) -> Orderbook:
    yes_raw = raw.get("yes") or raw.get("yes_dollars")
    no_raw = raw.get("no") or raw.get("no_dollars")
    return Orderbook(ticker=ticker, yes=_levels(yes_raw), no=_levels(no_raw))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_orderbook.py -k parse -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/kalshi_edge/kalshi/orderbook.py tests/test_orderbook.py
git commit -m "feat: parse and normalize raw kalshi orderbook"
```

---

## Task 4: Effective prices from the yes-bid/no-bid quirk

**Files:**
- Modify: `src/kalshi_edge/kalshi/orderbook.py`
- Test: `tests/test_orderbook.py` (append)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_orderbook.py (append)
from kalshi_edge.kalshi.orderbook import effective_prices


def test_effective_prices_reconstructs_ask_from_no_bid():
    # best yes bid 60c; best no bid 38c -> yes ask = 100-38 = 62c
    raw = {"yes": [[60, 100], [59, 50]], "no": [[38, 200], [37, 100]]}
    ep = effective_prices(parse_orderbook(raw, "T"))
    assert ep.yes_bid == 0.60
    assert ep.yes_ask == 0.62
    assert ep.yes_mid == 0.61
    assert round(ep.spread, 4) == 0.02


def test_effective_prices_handles_one_sided_book():
    ep_no_asks = effective_prices(parse_orderbook({"yes": [[60, 100]], "no": []}, "T"))
    assert ep_no_asks.yes_bid == 0.60 and ep_no_asks.yes_ask is None
    assert ep_no_asks.yes_mid is None and ep_no_asks.spread is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_orderbook.py -k effective -v`
Expected: FAIL — `ImportError: cannot import name 'effective_prices'`

- [ ] **Step 3: Add effective_prices**

```python
# src/kalshi_edge/kalshi/orderbook.py (append)
def effective_prices(ob: Orderbook) -> EffectivePrices:
    yes_bid = ob.yes[0].price / 100 if ob.yes else None
    yes_ask = (100 - ob.no[0].price) / 100 if ob.no else None
    if yes_bid is not None and yes_ask is not None:
        mid = (yes_bid + yes_ask) / 2
        spread = yes_ask - yes_bid
    else:
        mid = spread = None
    return EffectivePrices(yes_bid=yes_bid, yes_ask=yes_ask, yes_mid=mid, spread=spread)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_orderbook.py -k effective -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add src/kalshi_edge/kalshi/orderbook.py tests/test_orderbook.py
git commit -m "feat: reconstruct effective bid/ask/mid/spread"
```

---

## Task 5: Fill simulation (depth + slippage for a target size)

**Files:**
- Modify: `src/kalshi_edge/kalshi/orderbook.py`
- Test: `tests/test_orderbook.py` (append)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_orderbook.py (append)
from kalshi_edge.kalshi.orderbook import simulate_buy_yes, simulate_buy_no


def test_buy_yes_walks_no_book_and_computes_vwap_slippage():
    # buying YES consumes NO bids best-first: 38c(200)->ask 62c, 37c(150)->ask 63c
    raw = {"yes": [[60, 100]], "no": [[38, 200], [37, 150]]}
    fill = simulate_buy_yes(parse_orderbook(raw, "T"), size=250)
    # 200 @ 62c + 50 @ 63c = 15550c over 250 = 62.2c
    assert fill.filled == 250
    assert round(fill.avg_price, 4) == 0.622
    assert round(fill.slippage, 4) == 0.002  # vs best ask 0.62


def test_buy_yes_partial_when_book_too_thin():
    fill = simulate_buy_yes(parse_orderbook({"yes": [], "no": [[38, 100]]}, "T"), size=250)
    assert fill.filled == 100 and round(fill.avg_price, 4) == 0.62


def test_buy_yes_empty_book_returns_no_fill():
    fill = simulate_buy_yes(parse_orderbook({"yes": [], "no": []}, "T"), size=10)
    assert fill == Fill(filled=0, avg_price=None, slippage=None)


def test_buy_no_walks_yes_book():
    # buying NO consumes YES bids best-first: 60c->no ask 40c, 59c->no ask 41c
    raw = {"yes": [[60, 100], [59, 100]], "no": [[38, 200]]}
    fill = simulate_buy_no(parse_orderbook(raw, "T"), size=150)
    # 100 @ 40c + 50 @ 41c = 6050c over 150 = 40.333c
    assert fill.filled == 150 and round(fill.avg_price, 5) == 0.40333
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_orderbook.py -k "buy" -v`
Expected: FAIL — `ImportError: cannot import name 'simulate_buy_yes'`

- [ ] **Step 3: Add fill simulation**

```python
# src/kalshi_edge/kalshi/orderbook.py (append)
def _simulate(levels: tuple[OrderbookLevel, ...], size: int) -> Fill:
    """Walk `levels` (already best-first), where each level offers the opposite
    side at (100 - level.price) cents. Returns VWAP fill and slippage vs top."""
    remaining, cost_cents, filled, best = size, 0, 0, None
    for lvl in levels:
        ask_cents = 100 - lvl.price
        if best is None:
            best = ask_cents
        take = min(remaining, lvl.count)
        cost_cents += take * ask_cents
        filled += take
        remaining -= take
        if remaining == 0:
            break
    if filled == 0:
        return Fill(filled=0, avg_price=None, slippage=None)
    avg = (cost_cents / filled) / 100
    return Fill(filled=filled, avg_price=avg, slippage=avg - best / 100)


def simulate_buy_yes(ob: Orderbook, size: int) -> Fill:
    return _simulate(ob.no, size)   # buying YES consumes the NO-bid book


def simulate_buy_no(ob: Orderbook, size: int) -> Fill:
    return _simulate(ob.yes, size)  # buying NO consumes the YES-bid book
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_orderbook.py -k "buy" -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/kalshi_edge/kalshi/orderbook.py tests/test_orderbook.py
git commit -m "feat: simulate fills with vwap and slippage"
```

---

## Task 6: HTTP wrapper with retry/backoff

**Files:**
- Create: `src/kalshi_edge/config.py`
- Create: `src/kalshi_edge/kalshi/http.py`
- Test: `tests/test_http.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_http.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_http.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kalshi_edge.kalshi.http'`

- [ ] **Step 3: Write config and http wrapper**

```python
# src/kalshi_edge/config.py
# Public market-data base. Verify against docs.kalshi.com in Task 10's live smoke test;
# override via KalshiHTTP(base_url=...) if the host differs.
KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

# Soccer series tickers to scan. Seed from the live API in Task 10 (record_fixtures),
# then paste the real tickers here.
SOCCER_SERIES_TICKERS: list[str] = []
```

```python
# src/kalshi_edge/kalshi/http.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_http.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/kalshi_edge/config.py src/kalshi_edge/kalshi/http.py tests/test_http.py
git commit -m "feat: retrying http wrapper for kalshi"
```

---

## Task 7: KalshiClient (markets, orderbook, events/series, historical)

**Files:**
- Create: `src/kalshi_edge/kalshi/client.py`
- Test: `tests/test_client.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_client.py
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_client.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kalshi_edge.kalshi.client'`

- [ ] **Step 3: Write the client**

```python
# src/kalshi_edge/kalshi/client.py
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
        return parse_orderbook(body.get("orderbook") or {}, ticker=ticker)

    def get_events(self, *, series_ticker=None, status="open") -> list[dict]:
        params = {"status": status}
        if series_ticker:
            params["series_ticker"] = series_ticker
        return self._http.get_json("/events", params=params).get("events", [])

    def get_series(self, series_ticker: str) -> dict:
        return self._http.get_json(f"/series/{series_ticker}")["series"]

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_client.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add src/kalshi_edge/kalshi/client.py tests/test_client.py
git commit -m "feat: read-only kalshi client with pagination and historical access"
```

---

## Task 8: Today's-soccer-markets filter

**Files:**
- Create: `src/kalshi_edge/kalshi/soccer.py`
- Test: `tests/test_soccer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_soccer.py
from datetime import date
from kalshi_edge.kalshi.soccer import filter_markets_closing_on


def test_filter_keeps_only_markets_closing_on_target_date():
    markets = [
        {"ticker": "A", "close_time": "2026-07-03T18:00:00Z"},
        {"ticker": "B", "close_time": "2026-07-04T18:00:00Z"},
        {"ticker": "C", "close_time": "2026-07-03T23:59:00Z"},
    ]
    kept = [m["ticker"] for m in filter_markets_closing_on(markets, date(2026, 7, 3))]
    assert kept == ["A", "C"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_soccer.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kalshi_edge.kalshi.soccer'`

- [ ] **Step 3: Write the filter + discovery helper**

```python
# src/kalshi_edge/kalshi/soccer.py
from datetime import date, datetime
from collections.abc import Iterator
from kalshi_edge.kalshi.client import KalshiClient


def filter_markets_closing_on(markets: list[dict], target: date) -> list[dict]:
    out = []
    for m in markets:
        ct = m.get("close_time")
        if not ct:
            continue
        closes = datetime.fromisoformat(ct.replace("Z", "+00:00")).date()
        if closes == target:
            out.append(m)
    return out


def todays_soccer_markets(client: KalshiClient, series_tickers: list[str],
                          target: date) -> Iterator[dict]:
    """Yield open markets in the given soccer series that close on `target`."""
    for series in series_tickers:
        markets = list(client.iter_markets(series_ticker=series, status="open"))
        yield from filter_markets_closing_on(markets, target)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_soccer.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/kalshi_edge/kalshi/soccer.py tests/test_soccer.py
git commit -m "feat: filter today's soccer markets"
```

---

## Task 9: `pull_today` CLI

**Files:**
- Create: `scripts/pull_today.py`
- Test: `tests/test_client.py` (append — test the formatting function, not stdout)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_client.py (append)
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_client.py -k format_market_line -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.pull_today'`

- [ ] **Step 3: Write the CLI**

```python
# scripts/pull_today.py
from datetime import date, timezone, datetime
from kalshi_edge.config import KALSHI_BASE_URL, SOCCER_SERIES_TICKERS
from kalshi_edge.kalshi.http import KalshiHTTP
from kalshi_edge.kalshi.client import KalshiClient
from kalshi_edge.kalshi.soccer import todays_soccer_markets
from kalshi_edge.kalshi.orderbook import effective_prices
from kalshi_edge.kalshi.models import EffectivePrices


def _fmt(v: float | None) -> str:
    return f"{v:.2f}" if v is not None else "n/a"


def format_market_line(market: dict, ep: EffectivePrices) -> str:
    return (f"{market.get('ticker'):<28} {market.get('title', ''):<40} "
            f"bid={_fmt(ep.yes_bid)} ask={_fmt(ep.yes_ask)} "
            f"mid={_fmt(ep.yes_mid)} spr={_fmt(ep.spread)}")


def main() -> None:
    client = KalshiClient(http=KalshiHTTP(base_url=KALSHI_BASE_URL))
    today = datetime.now(timezone.utc).date()
    if not SOCCER_SERIES_TICKERS:
        print("No SOCCER_SERIES_TICKERS configured — run scripts/record_fixtures.py first.")
        return
    for market in todays_soccer_markets(client, SOCCER_SERIES_TICKERS, today):
        ob = client.get_orderbook(market["ticker"])
        print(format_market_line(market, effective_prices(ob)))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_client.py -k format_market_line -v`
Expected: PASS (2 tests). Add empty `tests/__init__.py` and `scripts/__init__.py` if the `scripts.pull_today` import fails to resolve.

- [ ] **Step 5: Commit**

```bash
git add scripts/pull_today.py tests/test_client.py
git commit -m "feat: pull_today cli for soccer effective prices"
```

---

## Task 10: Live smoke test + fixture recorder (verify against the real API)

**Files:**
- Create: `scripts/record_fixtures.py`
- Create: `tests/test_live_smoke.py`
- Create: `tests/conftest.py`
- Modify: `src/kalshi_edge/config.py` (paste real soccer series tickers discovered here)

- [ ] **Step 1: Add the `--run-live` pytest option**

```python
# tests/conftest.py
import pytest


def pytest_addoption(parser):
    parser.addoption("--run-live", action="store_true", default=False,
                     help="run tests marked 'live' against the real Kalshi API")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-live"):
        return
    skip = pytest.mark.skip(reason="needs --run-live")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)
```

- [ ] **Step 2: Write the live smoke test**

```python
# tests/test_live_smoke.py
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
```

- [ ] **Step 3: Run the live smoke test against the real API**

Run: `python -m pytest tests/test_live_smoke.py --run-live -v`
Expected: PASS. If it fails with a connection/host error, the `KALSHI_BASE_URL` host is wrong — check https://docs.kalshi.com and fix `config.py`, then re-run.

- [ ] **Step 4: Write and run the fixture recorder to discover soccer series + real JSON shapes**

```python
# scripts/record_fixtures.py
import json
from pathlib import Path
from kalshi_edge.config import KALSHI_BASE_URL
from kalshi_edge.kalshi.http import KalshiHTTP

OUT = Path("tests/fixtures")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    http = KalshiHTTP(base_url=KALSHI_BASE_URL)
    # 1) find soccer series
    series = http.get_json("/series", params={"category": "Sports"})
    (OUT / "series_sports.json").write_text(json.dumps(series, indent=2))
    # 2) grab a page of open markets + one orderbook to confirm response shape
    markets = http.get_json("/markets", params={"status": "open", "limit": 20})
    (OUT / "markets_open.json").write_text(json.dumps(markets, indent=2))
    ticker = markets["markets"][0]["ticker"]
    ob = http.get_json(f"/markets/{ticker}/orderbook")
    (OUT / "orderbook_sample.json").write_text(json.dumps(ob, indent=2))
    print(f"Wrote fixtures to {OUT}. Inspect series_sports.json for soccer/World Cup "
          f"series tickers and paste them into config.SOCCER_SERIES_TICKERS.")


if __name__ == "__main__":
    main()
```

Run: `python scripts/record_fixtures.py`
Expected: three JSON files in `tests/fixtures/`. Open `series_sports.json`, find the World Cup / soccer series tickers (e.g. moneyline, squad goals, player goals), and paste them into `SOCCER_SERIES_TICKERS` in `config.py`. Confirm `orderbook_sample.json` matches the `yes`/`no` (or `yes_dollars`/`no_dollars`) shape the parser expects; if it differs, add a failing parser test for the real shape and extend `parse_orderbook`.

- [ ] **Step 5: End-to-end manual check + commit**

Run: `python scripts/pull_today.py`
Expected: prints today's soccer markets with effective bid/ask/mid/spread (or the "no markets closing today" case, which is valid on a no-match day).

```bash
git add tests/conftest.py tests/test_live_smoke.py scripts/record_fixtures.py src/kalshi_edge/config.py tests/fixtures
git commit -m "feat: live smoke test and fixture recorder; seed soccer series tickers"
```

---

## Self-Review

**Spec coverage (against SP1 in the design doc):**
- Read-only REST client — Tasks 6, 7. ✓
- `GET /markets` filtered by series + today — Tasks 7, 8. ✓
- Orderbook effective bid/ask/mid/depth from yes-bid/no-bid quirk — Tasks 3, 4, 5. ✓
- Historical markets + candlesticks for the backtest — Task 7. ✓
- No order endpoints — enforced (client docstring; none written). ✓
- WebSocket live updates — **deferred to SP3** (polling via `pull_today` is sufficient for SP1's read-only milestone; noted here so it's not a silent gap).

**Placeholder scan:** No TBD/TODO; every code step has complete code. The only intentionally-empty value is `SOCCER_SERIES_TICKERS = []`, populated from live data in Task 10 (the real tickers can't be known until the API is queried).

**Type consistency:** `Orderbook`/`OrderbookLevel`/`EffectivePrices`/`Fill` used consistently across Tasks 2–9. `parse_orderbook(raw, ticker)`, `effective_prices(ob)`, `simulate_buy_yes/no(ob, size)` signatures match every call site. `KalshiClient(http=...)` and `KalshiHTTP(base_url=...)` consistent across client tests and CLI.

**Note on WebSocket:** SP1 delivers a polling read path. Live WebSocket streaming is SP3 scope — flagged, not forgotten.
