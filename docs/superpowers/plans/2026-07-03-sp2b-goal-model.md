# SP2b — Dixon-Coles Goal Model (v1) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the football data foundation (SP2a) into a per-match **joint score matrix** `P(home_goals, away_goals)`, match-outcome probabilities, and an analysis record — a time-decay-weighted Poisson strength model with the Dixon-Coles low-score correction.

**Architecture:** New `kalshi_edge/model/` subpackage. `poisson.py` is pure math (Dixon-Coles τ, score matrix, outcome probs). `strengths.py` computes time-weighted team attack/defense ratings + league mean + home-field factor from the SQLite matches. `goal_model.py` ties them into a `GoalModel` behind a clean interface. v1 uses **ratio-based strengths** (not full MLE) — labeled as such; full-MLE fit and fitted ρ are documented future improvements. The backtest (SP2e) validates it.

**Tech Stack:** Python 3.11+, stdlib `math`/`sqlite3` (no numpy needed at this size). Reuses SP2a's `kalshi_edge/data/` and the SP1 pytest config.

**Key formulas:**
- `λ_home = mu · attack_home · defense_away · hf`, `λ_away = mu · attack_away · defense_home / hf`
  where `hf = 1.0` on neutral ground, else the home-field factor. `mu` = league mean goals/team/match.
- Dixon-Coles τ adjusts only the four low-score cells for (0,0)/(0,1)/(1,0)/(1,1) dependency; ρ=0 → independent Poisson.
- Time-decay weight `= 0.5 ** (age_days / half_life_days)`, default half-life 730 days (~2yr).

---

## File Structure

```
src/kalshi_edge/model/
  __init__.py
  poisson.py      # dc_tau, score_matrix, outcome_probs  (pure)
  strengths.py    # decay_weight, team_strengths
  goal_model.py   # GoalModel
tests/
  test_poisson.py
  test_strengths.py
  test_goal_model.py
  test_model_live.py   # marked 'live' — builds model from real football.sqlite
```

---

## Task 1: Pure Poisson / Dixon-Coles math

**Files:**
- Create: `src/kalshi_edge/model/__init__.py` (empty), `src/kalshi_edge/model/poisson.py`
- Test: `tests/test_poisson.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_poisson.py
import math
from kalshi_edge.model.poisson import dc_tau, score_matrix, outcome_probs


def test_dc_tau_four_cells_and_default():
    lam, mu, rho = 1.3, 1.1, -0.1
    assert dc_tau(0, 0, lam, mu, rho) == 1 - lam * mu * rho
    assert dc_tau(0, 1, lam, mu, rho) == 1 + lam * rho
    assert dc_tau(1, 0, lam, mu, rho) == 1 + mu * rho
    assert dc_tau(1, 1, lam, mu, rho) == 1 - rho
    assert dc_tau(2, 3, lam, mu, rho) == 1.0  # outside the correction


def test_score_matrix_sums_to_one_and_is_independent_when_rho_zero():
    lam, mu = 1.4, 1.0
    M = score_matrix(lam, mu, rho=0.0, max_goals=10)
    total = sum(sum(row) for row in M)
    assert round(total, 6) == 1.0
    # rho=0 -> P(x,y) == Poisson(x;lam)*Poisson(y;mu) (up to renormalization tail)
    pois = lambda k, m: math.exp(-m) * m ** k / math.factorial(k)
    assert abs(M[1][2] - pois(1, lam) * pois(2, mu)) < 1e-4


def test_outcome_probs_symmetric_when_equal_rates():
    probs = outcome_probs(score_matrix(1.2, 1.2, rho=0.0))
    assert round(probs["home"], 6) == round(probs["away"], 6)
    assert round(probs["home"] + probs["draw"] + probs["away"], 6) == 1.0


def test_stronger_side_has_higher_win_prob():
    probs = outcome_probs(score_matrix(2.2, 0.7, rho=0.0))
    assert probs["home"] > probs["away"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_poisson.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kalshi_edge.model.poisson'`

- [ ] **Step 3: Write the pure math**

```python
# src/kalshi_edge/model/poisson.py
import math


def dc_tau(x: int, y: int, lam: float, mu: float, rho: float) -> float:
    """Dixon-Coles low-score dependency adjustment (1.0 outside the four cells)."""
    if x == 0 and y == 0:
        return 1 - lam * mu * rho
    if x == 0 and y == 1:
        return 1 + lam * rho
    if x == 1 and y == 0:
        return 1 + mu * rho
    if x == 1 and y == 1:
        return 1 - rho
    return 1.0


def _poisson(k: int, mean: float) -> float:
    return math.exp(-mean) * mean ** k / math.factorial(k)


def score_matrix(lam: float, mu: float, rho: float = 0.0, max_goals: int = 10) -> list[list[float]]:
    """Joint P(home=x, away=y) as a (max_goals+1) x (max_goals+1) matrix, renormalized."""
    M = [[_poisson(x, lam) * _poisson(y, mu) * dc_tau(x, y, lam, mu, rho)
          for y in range(max_goals + 1)] for x in range(max_goals + 1)]
    total = sum(sum(row) for row in M)
    return [[v / total for v in row] for row in M]


def outcome_probs(matrix: list[list[float]]) -> dict:
    """Collapse a joint score matrix into home-win / draw / away-win probabilities."""
    home = draw = away = 0.0
    for x, row in enumerate(matrix):
        for y, p in enumerate(row):
            if x > y:
                home += p
            elif x == y:
                draw += p
            else:
                away += p
    return {"home": home, "draw": draw, "away": away}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_poisson.py -v`
Expected: PASS (4)

- [ ] **Step 5: Commit**

```bash
git add src/kalshi_edge/model/__init__.py src/kalshi_edge/model/poisson.py tests/test_poisson.py
git commit -m "feat: dixon-coles poisson score matrix and outcome probs"
```

---

## Task 2: Time-decay team strengths

**Files:**
- Create: `src/kalshi_edge/model/strengths.py`
- Test: `tests/test_strengths.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_strengths.py
from kalshi_edge.data.cache import connect
from kalshi_edge.data.intl_results import load_results_csv
from kalshi_edge.model.strengths import decay_weight, team_strengths


def test_decay_weight_halves_at_half_life():
    assert decay_weight("2026-01-01", "2026-01-01", 730.0) == 1.0
    assert round(decay_weight("2024-01-02", "2026-01-01", 730.0), 3) == 0.5  # ~730 days
    assert decay_weight("2027-01-01", "2026-01-01", 730.0) == 0.0  # future -> 0


def test_team_strengths_ranks_dominant_team_higher():
    # Strong beats Weak heavily and repeatedly; Strong attack > Weak attack.
    rows = "date,home_team,away_team,home_score,away_score,tournament,city,country,neutral\n"
    for i in range(10):
        rows += f"2025-0{i%9+1}-01,Strong,Weak,4,0,Friendly,X,Y,TRUE\n"
        rows += f"2025-0{i%9+1}-15,Weak,Strong,0,3,Friendly,X,Y,TRUE\n"
    conn = connect(); load_results_csv(conn, rows)
    s = team_strengths(conn, ref_date="2025-10-01")
    assert s["mu"] > 0
    assert s["teams"]["Strong"]["attack"] > s["teams"]["Weak"]["attack"]
    assert s["teams"]["Strong"]["defense"] < s["teams"]["Weak"]["defense"]  # concedes less


def test_home_factor_reflects_home_scoring_edge():
    rows = "date,home_team,away_team,home_score,away_score,tournament,city,country,neutral\n"
    # Non-neutral games where home scores more than away on aggregate -> hf > 1
    for i in range(8):
        rows += f"2025-0{i%8+1}-01,A,B,2,1,Friendly,X,Y,FALSE\n"
    conn = connect(); load_results_csv(conn, rows)
    s = team_strengths(conn, ref_date="2025-09-01")
    assert s["home_factor"] > 1.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_strengths.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kalshi_edge.model.strengths'`

- [ ] **Step 3: Write the strengths computation**

```python
# src/kalshi_edge/model/strengths.py
from datetime import date as _date

DEFAULT_HALF_LIFE_DAYS = 730.0


def decay_weight(match_date: str, ref_date: str,
                 half_life_days: float = DEFAULT_HALF_LIFE_DAYS) -> float:
    age = (_date.fromisoformat(ref_date[:10]) - _date.fromisoformat(match_date[:10])).days
    if age < 0:
        return 0.0
    return 0.5 ** (age / half_life_days)


def team_strengths(conn, ref_date: str,
                   half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
                   since: str | None = None) -> dict:
    """Time-weighted attack/defense ratings (relative to league mean `mu`) + home factor.

    attack = (weighted goals scored per match) / mu
    defense = (weighted goals conceded per match) / mu   (lower = stronger defense)
    home_factor = sqrt(weighted home goals / weighted away goals) over non-neutral games
    """
    query = ("SELECT date, home_team, away_team, home_score, away_score, neutral "
             "FROM matches WHERE home_score IS NOT NULL AND away_score IS NOT NULL")
    args: list = []
    if since:
        query += " AND date >= ?"
        args.append(since)

    gs: dict = {}   # weighted goals scored
    gc: dict = {}   # weighted goals conceded
    w: dict = {}    # weighted appearances
    tot_goals = tot_team_matches = 0.0
    home_goals_w = away_goals_w = 0.0

    for r in conn.execute(query, args).fetchall():
        wt = decay_weight(r["date"], ref_date, half_life_days)
        if wt <= 0:
            continue
        h, a, hs, as_ = r["home_team"], r["away_team"], r["home_score"], r["away_score"]
        for team, scored, conceded in ((h, hs, as_), (a, as_, hs)):
            gs[team] = gs.get(team, 0.0) + wt * scored
            gc[team] = gc.get(team, 0.0) + wt * conceded
            w[team] = w.get(team, 0.0) + wt
        tot_goals += wt * (hs + as_)
        tot_team_matches += wt * 2
        if not r["neutral"]:
            home_goals_w += wt * hs
            away_goals_w += wt * as_

    mu = tot_goals / tot_team_matches if tot_team_matches else 0.0
    home_factor = (home_goals_w / away_goals_w) ** 0.5 if away_goals_w > 0 else 1.0
    teams = {
        team: {
            "attack": (gs[team] / w[team]) / mu if mu else 0.0,
            "defense": (gc[team] / w[team]) / mu if mu else 0.0,
            "weight": w[team],
        }
        for team in w if w[team] > 0
    }
    return {"mu": mu, "home_factor": home_factor, "teams": teams}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_strengths.py -v`
Expected: PASS (3)

- [ ] **Step 5: Commit**

```bash
git add src/kalshi_edge/model/strengths.py tests/test_strengths.py
git commit -m "feat: time-decay team attack/defense strengths"
```

---

## Task 3: GoalModel

**Files:**
- Create: `src/kalshi_edge/model/goal_model.py`
- Test: `tests/test_goal_model.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_goal_model.py
import pytest
from kalshi_edge.data.cache import connect
from kalshi_edge.data.intl_results import load_results_csv
from kalshi_edge.model.goal_model import GoalModel

ROWS = "date,home_team,away_team,home_score,away_score,tournament,city,country,neutral\n" + "".join(
    f"2025-0{i%9+1}-01,Strong,Weak,3,0,Friendly,X,Y,TRUE\n"
    f"2025-0{i%9+1}-15,Weak,Strong,0,3,Friendly,X,Y,TRUE\n" for i in range(10))


def _model():
    conn = connect(); load_results_csv(conn, ROWS)
    return GoalModel.from_db(conn, ref_date="2025-10-01")


def test_joint_matrix_sums_to_one():
    M = _model().joint_matrix("Strong", "Weak", neutral=True)
    assert round(sum(sum(r) for r in M), 6) == 1.0


def test_strong_team_favored():
    p = _model().match_probabilities("Strong", "Weak", neutral=True)
    assert p["home"] > 0.6 and p["home"] > p["away"]


def test_analysis_record_has_drivers():
    a = _model().analysis("Strong", "Weak", neutral=True)
    assert a["expected_goals"]["home"] > a["expected_goals"]["away"]
    assert "Strong" in a["strength"] and "Weak" in a["strength"]
    assert set(a["outcome_probs"]) == {"home", "draw", "away"}


def test_unknown_team_raises():
    with pytest.raises(ValueError):
        _model().expected_goals("Strong", "Nonexistent", neutral=True)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_goal_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kalshi_edge.model.goal_model'`

- [ ] **Step 3: Write the GoalModel**

```python
# src/kalshi_edge/model/goal_model.py
from kalshi_edge.model.poisson import score_matrix, outcome_probs
from kalshi_edge.model.strengths import team_strengths, DEFAULT_HALF_LIFE_DAYS


class GoalModel:
    """v1 ratio-based Poisson strength model with Dixon-Coles low-score correction.

    Not a full MLE fit (documented future improvement); validated by the backtest.
    """

    def __init__(self, mu: float, home_factor: float, teams: dict,
                 rho: float = 0.0, max_goals: int = 10):
        self.mu = mu
        self.home_factor = home_factor
        self.teams = teams
        self.rho = rho
        self.max_goals = max_goals

    @classmethod
    def from_db(cls, conn, ref_date: str, half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
                since: str | None = None, rho: float = 0.0, max_goals: int = 10) -> "GoalModel":
        s = team_strengths(conn, ref_date, half_life_days, since)
        return cls(s["mu"], s["home_factor"], s["teams"], rho=rho, max_goals=max_goals)

    def expected_goals(self, home: str, away: str, neutral: bool = True) -> tuple[float, float]:
        for t in (home, away):
            if t not in self.teams:
                raise ValueError(f"unknown team: {t!r}")
        th, ta = self.teams[home], self.teams[away]
        hf = 1.0 if neutral else self.home_factor
        lam = self.mu * th["attack"] * ta["defense"] * hf
        mu_ = self.mu * ta["attack"] * th["defense"] / hf
        return lam, mu_

    def joint_matrix(self, home: str, away: str, neutral: bool = True) -> list[list[float]]:
        lam, mu_ = self.expected_goals(home, away, neutral)
        return score_matrix(lam, mu_, self.rho, self.max_goals)

    def match_probabilities(self, home: str, away: str, neutral: bool = True) -> dict:
        return outcome_probs(self.joint_matrix(home, away, neutral))

    def analysis(self, home: str, away: str, neutral: bool = True) -> dict:
        lam, mu_ = self.expected_goals(home, away, neutral)
        return {
            "home": home, "away": away, "neutral": neutral,
            "expected_goals": {"home": lam, "away": mu_},
            "strength": {home: self.teams[home], away: self.teams[away]},
            "outcome_probs": self.match_probabilities(home, away, neutral),
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_goal_model.py -v`
Expected: PASS (4). Then run the full suite `python -m pytest -q`.

- [ ] **Step 5: Commit**

```bash
git add src/kalshi_edge/model/goal_model.py tests/test_goal_model.py
git commit -m "feat: GoalModel joint matrix, match probabilities, analysis record"
```

---

## Task 4: Live sanity check against a real matchup

**Files:**
- Create: `tests/test_model_live.py`

- [ ] **Step 1: Write the live test**

```python
# tests/test_model_live.py
import os
import pytest
from kalshi_edge.data.cache import connect
from kalshi_edge.model.goal_model import GoalModel

DB = "data/football.sqlite"


@pytest.mark.live
def test_model_favors_strong_side_on_real_data():
    if not os.path.exists(DB):
        pytest.skip("run scripts/build_db.py first")
    model = GoalModel.from_db(connect(DB), ref_date="2026-07-03", since="2016-01-01")
    # Argentina should be a heavy favorite over Cape Verde on neutral ground.
    p = model.match_probabilities("Argentina", "Cape Verde", neutral=True)
    assert p["home"] > 0.6
    assert p["home"] > p["away"] > 0
```

- [ ] **Step 2: Run it against the real DB**

Run: `python scripts/build_db.py && python -m pytest tests/test_model_live.py --run-live -v`
Expected: PASS. If `Cape Verde` isn't the exact team string in the dataset, adjust to the exact name (query `SELECT DISTINCT home_team FROM matches WHERE home_team LIKE 'Cape%'`).

- [ ] **Step 3: Commit**

```bash
git add tests/test_model_live.py
git commit -m "test: live sanity check of goal model on real matchup"
```

---

## Self-Review

**Spec coverage (against §3 goal_model):**
- Time-decay-weighted attack/defense strengths + Elo-style ratings — Task 2. ✓ (Elo *prior blend* is a later refinement; ratio strengths stand alone for v1.)
- Home advantage that zeroes on neutral ground — Task 2 (`home_factor`) + Task 3 (`neutral` flag). ✓
- Dixon-Coles low-score correction — Task 1 (`dc_tau`), wired via `rho`. ✓
- Joint `P(home_goals, away_goals)` matrix — Tasks 1, 3. ✓
- Analysis record (drivers behind the number) — Task 3 (`analysis`). ✓
- `GoalModel` interface for swappability — Task 3. ✓
- **Deferred (documented, not gaps):** full-MLE fit + fitted ρ; Elo prior blend for sparse teams;
  lineup/coach λ adjustments (SP2d enrichment); manual-override hook (SP2d).

**Placeholder scan:** No TBD/TODO; every step has complete code and exact commands.

**Type consistency:** `score_matrix(lam, mu, rho, max_goals)`, `outcome_probs(matrix)`,
`decay_weight(match_date, ref_date, half_life_days)`, `team_strengths(conn, ref_date, half_life_days, since)`
returning `{"mu","home_factor","teams"}`, and `GoalModel.from_db(...)` / `expected_goals` /
`joint_matrix` / `match_probabilities` / `analysis` are consistent across Tasks 1–4 and their tests.
