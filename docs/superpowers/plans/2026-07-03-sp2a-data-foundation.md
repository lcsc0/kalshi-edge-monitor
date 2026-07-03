# SP2a — Data Foundation (international results + goalscorers) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ingest the free, no-key international-football datasets (match results + goalscorers) into a local SQLite cache with query helpers for team goal rates and player goal counts — the data floor the Dixon-Coles goal model (SP2b) and player props build on.

**Architecture:** A `kalshi_edge/data/` subpackage: `cache.py` (SQLite schema/connection), `sources.py` (HTTP text download), `intl_results.py` (CSV → tables + query helpers). Offline tests use small inline CSV fixtures; a marked live test downloads the real files. No API key required for anything in SP2a.

**Tech Stack:** Python 3.11+, `httpx`, stdlib `csv`/`sqlite3`, `respx` (test). Reuses the existing package and pytest config from SP1.

**Data shapes (verified live 2026-07-03):**
- `results.csv` (49.5k rows): `date,home_team,away_team,home_score,away_score,tournament,city,country,neutral`
- `goalscorers.csv` (47.8k rows): `date,home_team,away_team,team,scorer,minute,own_goal,penalty`
- URLs: `https://raw.githubusercontent.com/martj42/international_results/master/{results,goalscorers}.csv`

---

## File Structure

```
src/kalshi_edge/data/
  __init__.py
  cache.py         # connect() -> sqlite3.Connection with schema
  sources.py       # download_text(url)
  intl_results.py  # load_results_csv, load_goalscorers_csv, query helpers
scripts/
  build_db.py      # download live CSVs into a local SQLite file
tests/
  test_data_cache.py
  test_data_sources.py
  test_intl_results.py
  test_data_live.py   # marked 'live'
```

---

## Task 1: Data package + SQLite schema

**Files:**
- Create: `src/kalshi_edge/data/__init__.py`, `src/kalshi_edge/data/cache.py`
- Test: `tests/test_data_cache.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_data_cache.py
from kalshi_edge.data.cache import connect


def test_connect_creates_expected_tables():
    conn = connect()  # in-memory
    names = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {"matches", "goals", "source_meta"} <= names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_data_cache.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kalshi_edge.data.cache'`

- [ ] **Step 3: Create the package + cache**

```python
# src/kalshi_edge/data/__init__.py
```
(empty)

```python
# src/kalshi_edge/data/cache.py
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS matches (
    date TEXT, home_team TEXT, away_team TEXT,
    home_score INTEGER, away_score INTEGER,
    tournament TEXT, city TEXT, country TEXT, neutral INTEGER
);
CREATE TABLE IF NOT EXISTS goals (
    date TEXT, home_team TEXT, away_team TEXT, team TEXT,
    scorer TEXT, minute INTEGER, own_goal INTEGER, penalty INTEGER
);
CREATE TABLE IF NOT EXISTS source_meta (
    source TEXT PRIMARY KEY, fetched_at TEXT, row_count INTEGER
);
CREATE INDEX IF NOT EXISTS idx_matches_home ON matches(home_team);
CREATE INDEX IF NOT EXISTS idx_matches_away ON matches(away_team);
CREATE INDEX IF NOT EXISTS idx_goals_scorer ON goals(scorer);
"""


def connect(path: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_data_cache.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/kalshi_edge/data/__init__.py src/kalshi_edge/data/cache.py tests/test_data_cache.py
git commit -m "feat: sqlite cache schema for football data"
```

---

## Task 2: HTTP text download

**Files:**
- Create: `src/kalshi_edge/data/sources.py`
- Test: `tests/test_data_sources.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_data_sources.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_data_sources.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kalshi_edge.data.sources'`

- [ ] **Step 3: Write the downloader**

```python
# src/kalshi_edge/data/sources.py
import httpx


def download_text(url: str, timeout: float = 30.0) -> str:
    resp = httpx.get(url, timeout=timeout, follow_redirects=True)
    resp.raise_for_status()
    return resp.text
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_data_sources.py -v`
Expected: PASS (2)

- [ ] **Step 5: Commit**

```bash
git add src/kalshi_edge/data/sources.py tests/test_data_sources.py
git commit -m "feat: http text downloader for data sources"
```

---

## Task 3: Load results + team goal-rate queries

**Files:**
- Create: `src/kalshi_edge/data/intl_results.py`
- Test: `tests/test_intl_results.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_intl_results.py
from kalshi_edge.data.cache import connect
from kalshi_edge.data.intl_results import (
    load_results_csv, team_matches, team_goal_rates,
)

RESULTS = (
    "date,home_team,away_team,home_score,away_score,tournament,city,country,neutral\n"
    "2026-06-01,Brazil,Chile,3,1,Friendly,Rio,Brazil,FALSE\n"
    "2026-06-05,Argentina,Brazil,2,2,Friendly,Buenos Aires,Argentina,FALSE\n"
    "2026-06-09,Brazil,Peru,0,1,Friendly,Sao Paulo,Brazil,TRUE\n"
)


def test_load_results_inserts_rows_and_records_meta():
    conn = connect()
    n = load_results_csv(conn, RESULTS)
    assert n == 3
    assert conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 3
    meta = conn.execute("SELECT row_count FROM source_meta WHERE source='results'").fetchone()
    assert meta[0] == 3


def test_team_matches_filters_and_orders():
    conn = connect(); load_results_csv(conn, RESULTS)
    ms = team_matches(conn, "Brazil")
    assert [m["date"] for m in ms] == ["2026-06-01", "2026-06-05", "2026-06-09"]
    assert team_matches(conn, "Brazil", since="2026-06-04")[0]["date"] == "2026-06-05"


def test_team_goal_rates_averages_scored_and_conceded():
    conn = connect(); load_results_csv(conn, RESULTS)
    # Brazil: scored 3,2,0 = 5/3 ; conceded 1,2,1 = 4/3
    scored, conceded = team_goal_rates(conn, "Brazil")
    assert round(scored, 4) == round(5 / 3, 4)
    assert round(conceded, 4) == round(4 / 3, 4)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_intl_results.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kalshi_edge.data.intl_results'`

- [ ] **Step 3: Write the loader + queries**

```python
# src/kalshi_edge/data/intl_results.py
import csv
import io
from datetime import datetime, timezone

RESULTS_URL = "https://raw.githubusercontent.com/martj42/international_results/master/results.csv"
GOALS_URL = "https://raw.githubusercontent.com/martj42/international_results/master/goalscorers.csv"


def _flag(v) -> int:
    return 1 if str(v).strip().upper() == "TRUE" else 0


def _int(v):
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def _record(conn, source: str, n: int) -> None:
    conn.execute("INSERT OR REPLACE INTO source_meta VALUES (?,?,?)",
                 (source, datetime.now(timezone.utc).isoformat(), n))


def load_results_csv(conn, text: str) -> int:
    rows = list(csv.DictReader(io.StringIO(text)))
    conn.executemany(
        "INSERT INTO matches VALUES (?,?,?,?,?,?,?,?,?)",
        [(r["date"], r["home_team"], r["away_team"],
          _int(r["home_score"]), _int(r["away_score"]),
          r["tournament"], r["city"], r["country"], _flag(r["neutral"])) for r in rows])
    _record(conn, "results", len(rows))
    conn.commit()
    return len(rows)


def team_matches(conn, team: str, since: str | None = None) -> list[dict]:
    query = "SELECT * FROM matches WHERE (home_team = ? OR away_team = ?)"
    args = [team, team]
    if since:
        query += " AND date >= ?"
        args.append(since)
    query += " ORDER BY date"
    return [dict(r) for r in conn.execute(query, args).fetchall()]


def team_goal_rates(conn, team: str, since: str | None = None) -> tuple[float, float]:
    """Average goals scored and conceded per completed match."""
    matches = [m for m in team_matches(conn, team, since)
               if m["home_score"] is not None and m["away_score"] is not None]
    if not matches:
        return (0.0, 0.0)
    scored = conceded = 0
    for m in matches:
        if m["home_team"] == team:
            scored += m["home_score"]; conceded += m["away_score"]
        else:
            scored += m["away_score"]; conceded += m["home_score"]
    n = len(matches)
    return (scored / n, conceded / n)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_intl_results.py -v`
Expected: PASS (3)

- [ ] **Step 5: Commit**

```bash
git add src/kalshi_edge/data/intl_results.py tests/test_intl_results.py
git commit -m "feat: load international results and team goal-rate queries"
```

---

## Task 4: Load goalscorers + player goal counts

**Files:**
- Modify: `src/kalshi_edge/data/intl_results.py`
- Test: `tests/test_intl_results.py` (append)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_intl_results.py (append)
from kalshi_edge.data.intl_results import load_goalscorers_csv, player_goal_count

GOALS = (
    "date,home_team,away_team,team,scorer,minute,own_goal,penalty\n"
    "2026-06-01,Brazil,Chile,Brazil,Neymar,23,FALSE,FALSE\n"
    "2026-06-01,Brazil,Chile,Brazil,Neymar,67,FALSE,TRUE\n"
    "2026-06-01,Brazil,Chile,Chile,Own Player,80,TRUE,FALSE\n"
    "2026-06-05,Argentina,Brazil,Brazil,Neymar,12,FALSE,FALSE\n"
)


def test_load_goalscorers_inserts_and_records_meta():
    conn = connect()
    assert load_goalscorers_csv(conn, GOALS) == 4
    assert conn.execute("SELECT COUNT(*) FROM goals").fetchone()[0] == 4


def test_player_goal_count_excludes_own_goals_and_respects_since():
    conn = connect(); load_goalscorers_csv(conn, GOALS)
    assert player_goal_count(conn, "Neymar") == 3
    assert player_goal_count(conn, "Neymar", since="2026-06-03") == 1
    assert player_goal_count(conn, "Own Player") == 0  # own goal excluded
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_intl_results.py -k "goalscorers or player_goal" -v`
Expected: FAIL — `ImportError: cannot import name 'load_goalscorers_csv'`

- [ ] **Step 3: Add the loader + query**

```python
# src/kalshi_edge/data/intl_results.py (append)
def load_goalscorers_csv(conn, text: str) -> int:
    rows = list(csv.DictReader(io.StringIO(text)))
    conn.executemany(
        "INSERT INTO goals VALUES (?,?,?,?,?,?,?,?)",
        [(r["date"], r["home_team"], r["away_team"], r["team"], r["scorer"],
          _int(r["minute"]), _flag(r["own_goal"]), _flag(r["penalty"])) for r in rows])
    _record(conn, "goalscorers", len(rows))
    conn.commit()
    return len(rows)


def player_goal_count(conn, scorer: str, since: str | None = None) -> int:
    query = "SELECT COUNT(*) FROM goals WHERE scorer = ? AND own_goal = 0"
    args = [scorer]
    if since:
        query += " AND date >= ?"
        args.append(since)
    return conn.execute(query, args).fetchone()[0]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_intl_results.py -k "goalscorers or player_goal" -v`
Expected: PASS (2). Then run the full file: `python -m pytest tests/test_intl_results.py -v`.

- [ ] **Step 5: Commit**

```bash
git add src/kalshi_edge/data/intl_results.py tests/test_intl_results.py
git commit -m "feat: load goalscorers and player goal counts"
```

---

## Task 5: `build_db` script + live download smoke test

**Files:**
- Create: `scripts/build_db.py`
- Create: `tests/test_data_live.py`

- [ ] **Step 1: Write the live smoke test (marked, skipped by default)**

```python
# tests/test_data_live.py
import pytest
from kalshi_edge.data.cache import connect
from kalshi_edge.data.sources import download_text
from kalshi_edge.data.intl_results import RESULTS_URL, load_results_csv, team_goal_rates


@pytest.mark.live
def test_live_results_download_and_query():
    conn = connect()
    n = load_results_csv(conn, download_text(RESULTS_URL))
    assert n > 40000  # dataset has ~49.5k rows
    scored, conceded = team_goal_rates(conn, "Brazil", since="2015-01-01")
    assert scored > 0 and conceded >= 0
```

- [ ] **Step 2: Run it live to confirm the real feed still parses**

Run: `python -m pytest tests/test_data_live.py --run-live -v`
Expected: PASS (uses the `--run-live` option already defined in `tests/conftest.py` from SP1).

- [ ] **Step 3: Write the build_db script**

```python
# scripts/build_db.py
from kalshi_edge.data.cache import connect
from kalshi_edge.data.sources import download_text
from kalshi_edge.data.intl_results import (
    RESULTS_URL, GOALS_URL, load_results_csv, load_goalscorers_csv,
)

DB_PATH = "data/football.sqlite"


def main() -> None:
    import os
    os.makedirs("data", exist_ok=True)
    conn = connect(DB_PATH)
    r = load_results_csv(conn, download_text(RESULTS_URL))
    g = load_goalscorers_csv(conn, download_text(GOALS_URL))
    print(f"Loaded {r} matches and {g} goals into {DB_PATH}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Build the real DB and confirm counts**

Run: `python scripts/build_db.py`
Expected: `Loaded ~49500 matches and ~47800 goals into data/football.sqlite`. (`data/` is gitignored from SP1 — the DB is a local artifact, not committed.)

- [ ] **Step 5: Commit**

```bash
git add scripts/build_db.py tests/test_data_live.py
git commit -m "feat: build_db script and live data smoke test"
```

---

## Self-Review

**Spec coverage (against §2 data_sources, no-key portion):**
- International results ingestion (Dixon-Coles input) — Tasks 1, 3. ✓
- Player goal data for props (from goalscorers, no FBref needed yet) — Task 4. ✓
- Local SQLite cache with `fetched_at` via `source_meta` — Tasks 1, 3, 4. ✓
- Team goal rates + player counts (query floor for SP2b model & props) — Tasks 3, 4. ✓
- Live verification against the real feed — Task 5. ✓
- **Deferred to later SP2 slices (noted, not gaps):** Elo prior, openfootball fixtures/squads, FBref
  minutes, and API-Football lineups/coaches — these land in SP2b (model) and SP2d (enrichment).

**Placeholder scan:** No TBD/TODO; every step has complete code and exact commands.

**Type consistency:** `connect()`, `load_results_csv(conn, text)`, `load_goalscorers_csv(conn, text)`,
`team_matches(conn, team, since)`, `team_goal_rates(conn, team, since)`,
`player_goal_count(conn, scorer, since)`, `download_text(url)` used consistently across Tasks 1–5.
`_flag`/`_int`/`_record` are shared private helpers defined once in Task 3 and reused in Task 4.
