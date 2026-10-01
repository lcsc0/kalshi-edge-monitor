# SP2d — Enrichment: analysis record + player props — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ground each matchup in real context — a rich **analysis record** (recent form, top scorers, coach, confirmed lineup) surfaced next to the model number — and price **player-goal props** (KXWCPLAYERGOALS). Per the SP2d decision: NO automatic team-λ adjustment; analysis is for the operator to judge, props use player rates.

**Architecture:** New `kalshi_edge/enrich/` package. The no-key core (form + top scorers from the existing SQLite `matches`/`goals`, and player-prop pricing from goal shares × model xG) is built and tested first. The `apifootball.py` client (coaches, confirmed lineups) reads `API_FOOTBALL_KEY` from env, caches every response in SQLite to respect the 100/day free limit, and is tested with `respx` mocks so tests never hit the real API. One live integration test at the end exercises the real key.

**Tech Stack:** Python 3.11+, `httpx`, `respx` (test), stdlib. Builds on SP2a (`data/`), SP2b (`model/`), SP2c (`pricer/`). Reads env via `os.environ` (a `.env` loader is added in Task 4). See the api-football-reference memory for endpoint shapes.

**Player-prop model:** `λ_player = goal_share × team_expected_goals`; `P(player scores ≥1) = 1 − exp(−λ_player)`. `goal_share` = player's goals ÷ team's total goals over a window (from the `goals` table, no key). `team_expected_goals` from the `GoalModel`.

---

## File Structure

```
src/kalshi_edge/enrich/
  __init__.py
  form.py         # recent_form, top_scorers  (from existing SQLite, no key)
  apifootball.py  # API-Football client w/ SQLite response cache (key from env)
  teams.py        # team name -> API-Football id map (+ manual overrides)
  analysis.py     # build_analysis(...) assembling the record
src/kalshi_edge/pricer/
  players.py      # player_goal_share, player_score_prob  (no key)
scripts/
  enrich_today.py # print analysis + top props for today's WC games
tests/
  test_form.py
  test_players.py
  test_apifootball.py
  test_analysis.py
  test_enrich_live.py   # marked 'live' — real API-Football + real DB
```

---

## Task 1: Player-prop pricing (no key)

**Files:**
- Create: `src/kalshi_edge/pricer/players.py`
- Test: `tests/test_players.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_players.py
import math
from kalshi_edge.data.cache import connect
from kalshi_edge.data.intl_results import load_goalscorers_csv
from kalshi_edge.pricer.players import player_goal_share, player_score_prob

GOALS = (
    "date,home_team,away_team,team,scorer,minute,own_goal,penalty\n"
    "2025-06-01,Portugal,Spain,Portugal,Ronaldo,10,FALSE,FALSE\n"
    "2025-06-01,Portugal,Spain,Portugal,Ronaldo,20,FALSE,FALSE\n"
    "2025-06-01,Portugal,Spain,Portugal,Silva,30,FALSE,FALSE\n"
    "2025-06-05,Portugal,France,Portugal,Ronaldo,40,FALSE,FALSE\n"
)


def test_player_goal_share_fraction_of_team_goals():
    conn = connect(); load_goalscorers_csv(conn, GOALS)
    # Portugal goals total = 4 (3 own + ... actually Ronaldo 3, Silva 1) = 4; Ronaldo 3/4
    assert round(player_goal_share(conn, "Ronaldo", "Portugal"), 4) == 0.75
    assert round(player_goal_share(conn, "Silva", "Portugal"), 4) == 0.25


def test_player_goal_share_zero_when_team_has_no_goals():
    conn = connect(); load_goalscorers_csv(conn, GOALS)
    assert player_goal_share(conn, "Ronaldo", "Nowhere") == 0.0


def test_player_score_prob_from_share_and_team_xg():
    # share 0.3, team xG 1.5 -> lambda 0.45 -> 1 - e^-0.45
    assert round(player_score_prob(0.3, 1.5), 6) == round(1 - math.exp(-0.45), 6)
    assert player_score_prob(0.0, 1.5) == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_players.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kalshi_edge.pricer.players'`

- [ ] **Step 3: Write the functions**

```python
# src/kalshi_edge/pricer/players.py
import math


def player_goal_share(conn, scorer: str, team: str, since: str | None = None) -> float:
    """Player's share of their team's total (non-own) goals over the window."""
    args_team = [team]
    args_player = [scorer, team]
    tail = ""
    if since:
        tail = " AND date >= ?"
        args_team.append(since)
        args_player.append(since)
    team_goals = conn.execute(
        "SELECT COUNT(*) FROM goals WHERE team = ? AND own_goal = 0" + tail, args_team
    ).fetchone()[0]
    if team_goals == 0:
        return 0.0
    player_goals = conn.execute(
        "SELECT COUNT(*) FROM goals WHERE scorer = ? AND team = ? AND own_goal = 0" + tail,
        args_player
    ).fetchone()[0]
    return player_goals / team_goals


def player_score_prob(goal_share: float, team_expected_goals: float) -> float:
    """P(player scores >= 1) = 1 - exp(-share * team_xg)."""
    lam = goal_share * team_expected_goals
    return 1 - math.exp(-lam)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_players.py -v`
Expected: PASS (3)

- [ ] **Step 5: Commit**

```bash
git add src/kalshi_edge/pricer/players.py tests/test_players.py
git commit -m "feat: player-goal prop pricing from goal share and team xg"
```

---

## Task 2: Recent form + top scorers (no key)

**Files:**
- Create: `src/kalshi_edge/enrich/__init__.py` (empty), `src/kalshi_edge/enrich/form.py`
- Test: `tests/test_form.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_form.py
from kalshi_edge.data.cache import connect
from kalshi_edge.data.intl_results import load_results_csv, load_goalscorers_csv
from kalshi_edge.enrich.form import recent_form, top_scorers

RESULTS = (
    "date,home_team,away_team,home_score,away_score,tournament,city,country,neutral\n"
    "2025-01-01,Portugal,A,2,0,Friendly,X,Y,TRUE\n"
    "2025-02-01,B,Portugal,1,1,Friendly,X,Y,TRUE\n"
    "2025-03-01,Portugal,C,0,3,Friendly,X,Y,TRUE\n"
)
GOALS = (
    "date,home_team,away_team,team,scorer,minute,own_goal,penalty\n"
    "2025-01-01,Portugal,A,Portugal,Ronaldo,10,FALSE,FALSE\n"
    "2025-01-01,Portugal,A,Portugal,Ronaldo,20,FALSE,FALSE\n"
    "2025-02-01,B,Portugal,Portugal,Silva,30,FALSE,FALSE\n"
)


def test_recent_form_returns_last_n_results_newest_first():
    conn = connect(); load_results_csv(conn, RESULTS)
    form = recent_form(conn, "Portugal", n=3)
    assert [f["result"] for f in form] == ["L", "D", "W"]  # 03-01 loss, 02-01 draw, 01-01 win
    assert form[0]["date"] == "2025-03-01"
    assert form[0]["goals_for"] == 0 and form[0]["goals_against"] == 3


def test_top_scorers_ranked_by_goals():
    conn = connect(); load_goalscorers_csv(conn, GOALS)
    scorers = top_scorers(conn, "Portugal", limit=5)
    assert scorers[0]["scorer"] == "Ronaldo" and scorers[0]["goals"] == 2
    assert scorers[1]["scorer"] == "Silva" and scorers[1]["goals"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_form.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kalshi_edge.enrich.form'`

- [ ] **Step 3: Write form.py**

```python
# src/kalshi_edge/enrich/form.py
def recent_form(conn, team: str, n: int = 5, before: str | None = None) -> list[dict]:
    """Last `n` completed matches for team, newest first, each with W/D/L + goals."""
    query = ("SELECT date, home_team, away_team, home_score, away_score FROM matches "
             "WHERE (home_team = ? OR away_team = ?) "
             "AND home_score IS NOT NULL AND away_score IS NOT NULL")
    args = [team, team]
    if before:
        query += " AND date < ?"
        args.append(before)
    query += " ORDER BY date DESC LIMIT ?"
    args.append(n)
    out = []
    for r in conn.execute(query, args).fetchall():
        if r["home_team"] == team:
            gf, ga = r["home_score"], r["away_score"]
            opp = r["away_team"]
        else:
            gf, ga = r["away_score"], r["home_score"]
            opp = r["home_team"]
        result = "W" if gf > ga else ("D" if gf == ga else "L")
        out.append({"date": r["date"], "opponent": opp, "goals_for": gf,
                    "goals_against": ga, "result": result})
    return out


def top_scorers(conn, team: str, limit: int = 5, since: str | None = None) -> list[dict]:
    """Most prolific scorers for the team (non-own goals) over the window."""
    query = ("SELECT scorer, COUNT(*) AS goals FROM goals "
             "WHERE team = ? AND own_goal = 0")
    args = [team]
    if since:
        query += " AND date >= ?"
        args.append(since)
    query += " GROUP BY scorer ORDER BY goals DESC, scorer LIMIT ?"
    args.append(limit)
    return [{"scorer": r["scorer"], "goals": r["goals"]}
            for r in conn.execute(query, args).fetchall()]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_form.py -v`
Expected: PASS (2)

- [ ] **Step 5: Commit**

```bash
git add src/kalshi_edge/enrich/__init__.py src/kalshi_edge/enrich/form.py tests/test_form.py
git commit -m "feat: recent form and top scorers from results data"
```

---

## Task 3: API-Football client with SQLite cache (key from env)

**Files:**
- Create: `src/kalshi_edge/enrich/apifootball.py`
- Test: `tests/test_apifootball.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_apifootball.py
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
    assert route.call_count == 1  # second call hit the SQLite cache


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_apifootball.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kalshi_edge.enrich.apifootball'`

- [ ] **Step 3: Write the client**

```python
# src/kalshi_edge/enrich/apifootball.py
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
        if errors:  # API-Football returns 200 with a populated errors on auth/limit failure
            raise RuntimeError(f"API-Football error: {errors}")
        data = body.get("response", [])
        if self.conn is not None:
            self.conn.execute(
                "INSERT OR REPLACE INTO api_cache VALUES (?,?,?)",
                (ck, json.dumps(data), datetime.now(timezone.utc).isoformat()))
            self.conn.commit()
        return data
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_apifootball.py -v`
Expected: PASS (3)

- [ ] **Step 5: Commit**

```bash
git add src/kalshi_edge/enrich/apifootball.py tests/test_apifootball.py
git commit -m "feat: cached read-only api-football client"
```

---

## Task 4: Analysis record assembly + `.env` loader

**Files:**
- Create: `src/kalshi_edge/enrich/teams.py`, `src/kalshi_edge/enrich/analysis.py`
- Modify: `src/kalshi_edge/config.py` (add a tiny `.env` loader)
- Test: `tests/test_analysis.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_analysis.py
from kalshi_edge.data.cache import connect
from kalshi_edge.data.intl_results import load_results_csv, load_goalscorers_csv
from kalshi_edge.model.goal_model import GoalModel
from kalshi_edge.enrich.analysis import build_analysis

ROWS = "date,home_team,away_team,home_score,away_score,tournament,city,country,neutral\n" + "".join(
    f"2025-0{i%9+1}-01,Portugal,Spain,2,1,Friendly,X,Y,TRUE\n"
    f"2025-0{i%9+1}-15,Spain,Portugal,1,2,Friendly,X,Y,TRUE\n" for i in range(6))
GOALS = "date,home_team,away_team,team,scorer,minute,own_goal,penalty\n" + "".join(
    f"2025-0{i%9+1}-01,Portugal,Spain,Portugal,Ronaldo,10,FALSE,FALSE\n" for i in range(6))


def test_build_analysis_combines_model_form_and_scorers():
    conn = connect(); load_results_csv(conn, ROWS); load_goalscorers_csv(conn, GOALS)
    model = GoalModel.from_db(conn, ref_date="2025-10-01")
    a = build_analysis(conn, model, "Portugal", "Spain", neutral=True)
    assert set(a["outcome_probs"]) == {"home", "draw", "away"}
    assert "form" in a and "Portugal" in a["form"] and len(a["form"]["Portugal"]) > 0
    assert a["top_scorers"]["Portugal"][0]["scorer"] == "Ronaldo"
    assert "top_props" in a  # player score probabilities
    assert a["coaches"] == {"Portugal": None, "Spain": None}  # no api client passed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_analysis.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kalshi_edge.enrich.analysis'`

- [ ] **Step 3: Write teams.py, analysis.py, and the .env loader**

```python
# src/kalshi_edge/enrich/teams.py
# Manual overrides where the results dataset name differs from API-Football's.
NAME_OVERRIDES: dict[str, str] = {}


def resolve_team_id(api, name: str) -> int | None:
    """Return the API-Football national-team id for a dataset team name, or None."""
    query = NAME_OVERRIDES.get(name, name)
    for row in api.get("/teams", {"search": query}):
        team = row.get("team", {})
        if team.get("national"):
            return team.get("id")
    return None
```

```python
# src/kalshi_edge/enrich/analysis.py
from kalshi_edge.enrich.form import recent_form, top_scorers
from kalshi_edge.enrich.teams import resolve_team_id
from kalshi_edge.pricer.players import player_goal_share, player_score_prob


def _coach(api, team: str):
    if api is None:
        return None
    team_id = resolve_team_id(api, team)
    if team_id is None:
        return None
    coaches = api.get("/coachs", {"team": str(team_id)})
    return coaches[0].get("name") if coaches else None


def build_analysis(conn, model, home: str, away: str, neutral: bool = True,
                   api=None, since: str | None = None) -> dict:
    base = model.analysis(home, away, neutral)
    lam, mu = base["expected_goals"]["home"], base["expected_goals"]["away"]
    props = []
    for team, team_xg in ((home, lam), (away, mu)):
        for sc in top_scorers(conn, team, limit=3, since=since):
            share = player_goal_share(conn, sc["scorer"], team, since)
            props.append({"team": team, "scorer": sc["scorer"],
                          "score_prob": player_score_prob(share, team_xg)})
    props.sort(key=lambda p: p["score_prob"], reverse=True)
    return {
        **base,
        "form": {home: recent_form(conn, home), away: recent_form(conn, away)},
        "top_scorers": {home: top_scorers(conn, home), away: top_scorers(conn, away)},
        "coaches": {home: _coach(api, home), away: _coach(api, away)},
        "top_props": props,
    }
```

In `src/kalshi_edge/config.py`, append a minimal `.env` loader (no new dependency):

```python
# src/kalshi_edge/config.py (append)
import os
from pathlib import Path


def load_env(path: str = ".env") -> None:
    """Load KEY=VALUE lines from a .env file into os.environ (no overwrite)."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_analysis.py -v`
Expected: PASS. Then run the full suite `python -m pytest -q`.

- [ ] **Step 5: Commit**

```bash
git add src/kalshi_edge/enrich/teams.py src/kalshi_edge/enrich/analysis.py src/kalshi_edge/config.py tests/test_analysis.py
git commit -m "feat: analysis record assembly and .env loader"
```

---

## Task 5: `enrich_today` script + live integration

**Files:**
- Create: `scripts/enrich_today.py`
- Create: `tests/test_enrich_live.py`

- [ ] **Step 1: Write the live integration test (uses real key + DB, few requests)**

```python
# tests/test_enrich_live.py
import os
import pytest
from kalshi_edge.config import load_env
from kalshi_edge.data.cache import connect
from kalshi_edge.enrich.apifootball import ApiFootball
from kalshi_edge.enrich.teams import resolve_team_id

DB = "data/football.sqlite"


@pytest.mark.live
def test_resolve_real_national_team_id():
    load_env()
    if not os.environ.get("API_FOOTBALL_KEY"):
        pytest.skip("no API_FOOTBALL_KEY")
    api = ApiFootball(conn=connect(DB) if os.path.exists(DB) else connect())
    assert resolve_team_id(api, "Portugal") == 27  # national side
```

- [ ] **Step 2: Run the live test**

Run: `python -m pytest tests/test_enrich_live.py --run-live -v`
Expected: PASS (Portugal national team id = 27). Uses ~1 request (cached after).

- [ ] **Step 3: Write the enrich_today script**

```python
# scripts/enrich_today.py
from datetime import datetime, timezone
from kalshi_edge.config import load_env
from kalshi_edge.data.cache import connect
from kalshi_edge.model.goal_model import GoalModel
from kalshi_edge.enrich.apifootball import ApiFootball
from kalshi_edge.enrich.analysis import build_analysis

DB = "data/football.sqlite"


def main(home: str, away: str) -> None:
    load_env()
    conn = connect(DB)
    model = GoalModel.from_db(conn, ref_date=str(datetime.now(timezone.utc).date()),
                              since="2016-01-01")
    api = ApiFootball(conn=conn)
    a = build_analysis(conn, model, home, away, neutral=True, api=api)
    p = a["outcome_probs"]
    print(f"{home} vs {away}  ({a['expected_goals']['home']:.2f}-{a['expected_goals']['away']:.2f} xG)")
    print(f"  win prob : {home} {p['home']:.3f} | draw {p['draw']:.3f} | {away} {p['away']:.3f}")
    print(f"  coaches  : {a['coaches']}")
    for team in (home, away):
        form = "".join(f["result"] for f in a["form"][team][:5])
        print(f"  {team} form (recent->old): {form}")
    print("  top score props:")
    for pr in a["top_props"][:6]:
        print(f"    {pr['scorer']:<20} ({pr['team']}) P(scores)={pr['score_prob']:.3f}")


if __name__ == "__main__":
    import sys
    main(sys.argv[1], sys.argv[2])
```

- [ ] **Step 4: Run it on today's real matchup**

Run: `python scripts/enrich_today.py Portugal Spain`
Expected: prints win probs, coaches, recent form strings, and top player score props. Record that it works end-to-end.

- [ ] **Step 5: Commit**

```bash
git add scripts/enrich_today.py tests/test_enrich_live.py
git commit -m "feat: enrich_today script and live api-football check"
```

---

## Self-Review

**Spec coverage (against §2/§3a enrichment, SP2d decision = analysis + props only):**
- Recent form + top scorers from existing data — Task 2. ✓
- Confirmed coach (and lineup-ready client) via API-Football, cached for the 100/day limit — Tasks 3, 4. ✓
- Player-goal props priced from real player rates — Tasks 1, 4. ✓
- Analysis record surfaced with each matchup (the grounding) — Task 4, script Task 5. ✓
- NO automatic team-λ adjustment (per the decision) — enforced: `build_analysis` never mutates the model. ✓
- API key from env, never committed; responses cached — Tasks 3, 4. ✓
- **Deferred (documented):** confirmed-XI *presence* filtering of props (needs `/fixtures/lineups` + fixture-id resolution — a later refinement); automatic λ adjustment (explicitly out per the SP2d decision).

**Placeholder scan:** No TBD/TODO; every step has complete code + commands. Live tests may use ~1-2 API requests (cached thereafter).

**Type consistency:** `player_goal_share(conn, scorer, team, since)`, `player_score_prob(share, xg)`,
`recent_form(conn, team, n, before)`, `top_scorers(conn, team, limit, since)`,
`ApiFootball(api_key, conn, http).get(path, params) -> list`, `resolve_team_id(api, name)`,
`build_analysis(conn, model, home, away, neutral, api, since)` consistent across Tasks 1-5 and tests.
