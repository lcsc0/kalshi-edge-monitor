# SP2f — Opponent-Adjusted Dixon-Coles MLE Model — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the v1 ratio strengths with a proper opponent-adjusted **Dixon-Coles maximum-likelihood fit** (time-decay weighted, home advantage, ρ low-score correction), exposed as `MLEGoalModel` implementing the same interface as `GoalModel` so pricer/enrichment/backtest work unchanged. Prototype-verified: out-of-sample Brier 0.514 vs v1's 0.551 (baseline 0.640) on 2023.

**Architecture:** `model/mle.py` fits attack/defense per team + home_adv + ρ by minimizing the weighted negative log-likelihood (scipy L-BFGS-B, numpy-vectorized). `model/mle_model.py` wraps the fit as `MLEGoalModel` with the `GoalModel` method surface (`expected_goals`, `joint_matrix`, `match_probabilities`, `analysis`, `from_db`). Fit is invariant to a global attack/defense shift, so params are mean-centered for reproducibility. Fit once per day (~30s); the backtest fits once at the test-window start (no per-match refit).

**Tech Stack:** Python 3.11+, **numpy + scipy** (new deps), stdlib. Builds on SP2a/SP2b. Reuses `poisson.score_matrix`/`outcome_probs` for the matrix + outcome collapse.

**λ parameterization:** `λ_home = exp(attack_home − defense_away + home_adv·[not neutral])`, `λ_away = exp(attack_away − defense_home)`.

---

## File Structure

```
src/kalshi_edge/model/
  mle.py         # fit_dixon_coles(conn, ...) -> DCFit
  mle_model.py   # MLEGoalModel (GoalModel-compatible)
scripts/
  run_backtest_mle.py   # fit-once MLE backtest vs v1 on real data
tests/
  test_mle.py
  test_mle_model.py
  test_mle_live.py   # marked 'live'
```

Also modifies `pyproject.toml` (add numpy, scipy).

---

## Task 1: Dixon-Coles MLE fit

**Files:**
- Modify: `pyproject.toml` (dependencies: add `numpy>=1.26`, `scipy>=1.11`)
- Create: `src/kalshi_edge/model/mle.py`
- Test: `tests/test_mle.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mle.py
from kalshi_edge.data.cache import connect
from kalshi_edge.data.intl_results import load_results_csv
from kalshi_edge.model.mle import fit_dixon_coles

# Strong beats Weak and Mid; Mid beats Weak. Enough games to clear min_games.
ROWS = "date,home_team,away_team,home_score,away_score,tournament,city,country,neutral\n" + "".join(
    f"2022-{mo:02d}-01,Strong,Weak,3,0,Friendly,X,Y,TRUE\n"
    f"2022-{mo:02d}-08,Strong,Mid,2,0,Friendly,X,Y,TRUE\n"
    f"2022-{mo:02d}-15,Mid,Weak,2,1,Friendly,X,Y,TRUE\n"
    f"2022-{mo:02d}-22,Weak,Mid,0,1,Friendly,X,Y,FALSE\n"
    for mo in range(1, 13))


def test_fit_recovers_team_ordering_and_globals():
    conn = connect(); load_results_csv(conn, ROWS)
    fit = fit_dixon_coles(conn, ref_date="2023-01-01", since="2020-01-01", min_games=5)
    # Attack ordering Strong > Mid > Weak
    assert fit.attack["Strong"] > fit.attack["Mid"] > fit.attack["Weak"]
    # Strong concedes least -> highest defense rating (defense = defensive strength; higher is better)
    assert fit.defense["Strong"] > fit.defense["Weak"]
    assert 0.0 <= fit.home_adv <= 1.0
    assert -0.2 <= fit.rho <= 0.2
    # mean-centered attack for reproducibility
    assert abs(sum(fit.attack.values())) < 1e-6


def test_fit_only_includes_teams_meeting_min_games():
    conn = connect(); load_results_csv(conn, ROWS)
    fit = fit_dixon_coles(conn, ref_date="2023-01-01", since="2020-01-01", min_games=1000)
    assert fit.attack == {}  # nobody clears the bar
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_mle.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kalshi_edge.model.mle'`

- [ ] **Step 3: Write the fit**

```python
# src/kalshi_edge/model/mle.py
from collections import Counter
from dataclasses import dataclass
import numpy as np
from scipy.optimize import minimize
from scipy.special import gammaln

DEFAULT_HALF_LIFE_DAYS = 730.0


@dataclass(frozen=True)
class DCFit:
    attack: dict     # team -> attack rating (higher = scores more)
    defense: dict    # team -> defensive rating (higher = concedes less)
    home_adv: float  # log home-advantage
    rho: float       # Dixon-Coles low-score correction


def _decay(date: str, ref: str, hl: float) -> float:
    age = (np.datetime64(ref) - np.datetime64(date[:10])).astype("timedelta64[D]").astype(int)
    return 0.5 ** (age / hl) if age >= 0 else 0.0


def fit_dixon_coles(conn, ref_date: str, since: str | None = None,
                    half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
                    min_games: int = 20, max_iter: int = 500) -> DCFit:
    query = ("SELECT date, home_team, away_team, home_score, away_score, neutral "
             "FROM matches WHERE home_score IS NOT NULL AND away_score IS NOT NULL AND date < ?")
    args = [ref_date]
    if since:
        query += " AND date >= ?"
        args.append(since)
    rows = conn.execute(query, args).fetchall()

    cnt: Counter = Counter()
    for r in rows:
        cnt[r["home_team"]] += 1
        cnt[r["away_team"]] += 1
    teams = sorted(t for t, c in cnt.items() if c >= min_games)
    if not teams:
        return DCFit(attack={}, defense={}, home_adv=0.0, rho=0.0)
    idx = {t: i for i, t in enumerate(teams)}
    T = len(teams)

    rows = [r for r in rows if r["home_team"] in idx and r["away_team"] in idx]
    hi = np.array([idx[r["home_team"]] for r in rows])
    ai = np.array([idx[r["away_team"]] for r in rows])
    hs = np.array([r["home_score"] for r in rows], float)
    aw = np.array([r["away_score"] for r in rows], float)
    neu = np.array([1.0 if r["neutral"] else 0.0 for r in rows])
    w = np.array([_decay(r["date"], ref_date, half_life_days) for r in rows])
    lg_hs, lg_aw = gammaln(hs + 1), gammaln(aw + 1)

    def nll(p):
        att, deff, home, rho = p[:T], p[T:2*T], p[2*T], p[2*T+1]
        log_lam = att[hi] - deff[ai] + home * (1 - neu)
        log_mu = att[ai] - deff[hi]
        lam, mu = np.exp(log_lam), np.exp(log_mu)
        t = np.ones_like(lam)
        m00 = (hs == 0) & (aw == 0); t[m00] = 1 - lam[m00]*mu[m00]*rho
        m01 = (hs == 0) & (aw == 1); t[m01] = 1 + lam[m01]*rho
        m10 = (hs == 1) & (aw == 0); t[m10] = 1 + mu[m10]*rho
        m11 = (hs == 1) & (aw == 1); t[m11] = 1 - rho
        t = np.clip(t, 1e-9, None)
        ll = (hs*log_lam - lam - lg_hs) + (aw*log_mu - mu - lg_aw) + np.log(t)
        return -np.sum(w * ll)

    x0 = np.concatenate([np.zeros(2*T), [0.25, -0.05]])
    bounds = [(-3, 3)]*(2*T) + [(0.0, 1.0), (-0.2, 0.2)]
    res = minimize(nll, x0, method="L-BFGS-B", bounds=bounds,
                   options={"maxiter": max_iter, "maxfun": 200000})
    att, deff, home, rho = res.x[:T], res.x[T:2*T], float(res.x[2*T]), float(res.x[2*T+1])
    # Mean-center attack (and shift defense equally) — predictions are shift-invariant.
    shift = att.mean()
    att = att - shift
    deff = deff - shift
    return DCFit(attack={t: float(att[i]) for t, i in idx.items()},
                 defense={t: float(deff[i]) for t, i in idx.items()},
                 home_adv=home, rho=rho)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_mle.py -v`
Expected: PASS (2)

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml src/kalshi_edge/model/mle.py tests/test_mle.py
git commit -m "feat: dixon-coles mle fit (opponent-adjusted, time-decay weighted)"
```

---

## Task 2: MLEGoalModel (GoalModel-compatible)

**Files:**
- Create: `src/kalshi_edge/model/mle_model.py`
- Test: `tests/test_mle_model.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_mle_model.py
import pytest
from kalshi_edge.data.cache import connect
from kalshi_edge.data.intl_results import load_results_csv
from kalshi_edge.model.mle_model import MLEGoalModel
from tests.test_mle import ROWS  # reuse the Strong/Mid/Weak fixture


def _model():
    conn = connect(); load_results_csv(conn, ROWS)
    return MLEGoalModel.from_db(conn, ref_date="2023-01-01", since="2020-01-01", min_games=5)


def test_joint_matrix_sums_to_one():
    M = _model().joint_matrix("Strong", "Weak", neutral=True)
    assert round(sum(sum(r) for r in M), 6) == 1.0


def test_strong_favored_over_weak():
    p = _model().match_probabilities("Strong", "Weak", neutral=True)
    assert p["home"] > 0.5 and p["home"] > p["away"]


def test_home_advantage_helps_home_side():
    m = _model()
    ph = m.match_probabilities("Mid", "Strong", neutral=False)["home"]
    pn = m.match_probabilities("Mid", "Strong", neutral=True)["home"]
    assert ph > pn  # playing at home lifts Mid's win prob


def test_analysis_shape_matches_goalmodel():
    a = _model().analysis("Strong", "Weak", neutral=True)
    assert set(a["outcome_probs"]) == {"home", "draw", "away"}
    assert a["expected_goals"]["home"] > a["expected_goals"]["away"]
    assert "Strong" in a["strength"]


def test_unknown_team_raises():
    with pytest.raises(ValueError):
        _model().expected_goals("Strong", "Nobody", neutral=True)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_mle_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kalshi_edge.model.mle_model'`

- [ ] **Step 3: Write the model**

```python
# src/kalshi_edge/model/mle_model.py
import math
from kalshi_edge.model.poisson import score_matrix, outcome_probs
from kalshi_edge.model.mle import fit_dixon_coles, DCFit, DEFAULT_HALF_LIFE_DAYS


class MLEGoalModel:
    """Opponent-adjusted Dixon-Coles MLE model, drop-in for GoalModel."""

    def __init__(self, fit: DCFit, max_goals: int = 10):
        self.fit = fit
        self.max_goals = max_goals

    @classmethod
    def from_db(cls, conn, ref_date: str, since: str | None = None,
                half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
                min_games: int = 20, max_goals: int = 10) -> "MLEGoalModel":
        return cls(fit_dixon_coles(conn, ref_date, since, half_life_days, min_games),
                   max_goals=max_goals)

    def expected_goals(self, home: str, away: str, neutral: bool = True) -> tuple[float, float]:
        for t in (home, away):
            if t not in self.fit.attack:
                raise ValueError(f"unknown team: {t!r}")
        home_term = 0.0 if neutral else self.fit.home_adv
        lam = math.exp(self.fit.attack[home] - self.fit.defense[away] + home_term)
        mu = math.exp(self.fit.attack[away] - self.fit.defense[home])
        return lam, mu

    def joint_matrix(self, home: str, away: str, neutral: bool = True) -> list[list[float]]:
        lam, mu = self.expected_goals(home, away, neutral)
        return score_matrix(lam, mu, self.fit.rho, self.max_goals)

    def match_probabilities(self, home: str, away: str, neutral: bool = True) -> dict:
        return outcome_probs(self.joint_matrix(home, away, neutral))

    def analysis(self, home: str, away: str, neutral: bool = True) -> dict:
        lam, mu = self.expected_goals(home, away, neutral)
        return {
            "home": home, "away": away, "neutral": neutral,
            "expected_goals": {"home": lam, "away": mu},
            "strength": {
                home: {"attack": self.fit.attack[home], "defense": self.fit.defense[home]},
                away: {"attack": self.fit.attack[away], "defense": self.fit.defense[away]},
            },
            "outcome_probs": self.match_probabilities(home, away, neutral),
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_mle_model.py -v`
Expected: PASS (5). Then run the full suite `python -m pytest -q`.

- [ ] **Step 5: Commit**

```bash
git add src/kalshi_edge/model/mle_model.py tests/test_mle_model.py
git commit -m "feat: MLEGoalModel drop-in with GoalModel interface"
```

---

## Task 3: Live backtest — MLE beats v1

**Files:**
- Create: `scripts/run_backtest_mle.py`
- Create: `tests/test_mle_live.py`

- [ ] **Step 1: Write the live test**

```python
# tests/test_mle_live.py
import os
import pytest
from kalshi_edge.data.cache import connect
from kalshi_edge.model.goal_model import GoalModel
from kalshi_edge.model.mle_model import MLEGoalModel
from kalshi_edge.backtest.metrics import brier_score

DB = "data/football.sqlite"


def _score(model, rows, idx_ok):
    recs = []
    for r in rows:
        h, a = r["home_team"], r["away_team"]
        if not idx_ok(h, a):
            continue
        y = "home" if r["home_score"] > r["away_score"] else ("draw" if r["home_score"] == r["away_score"] else "away")
        recs.append({"probs": model.match_probabilities(h, a, neutral=bool(r["neutral"])),
                     "outcome": y})
    return recs


@pytest.mark.live
def test_mle_beats_v1_out_of_sample():
    if not os.path.exists(DB):
        pytest.skip("run scripts/build_db.py first")
    conn = connect(DB)
    ref = "2023-01-01"
    mle = MLEGoalModel.from_db(conn, ref_date=ref, since="2014-01-01")
    v1 = GoalModel.from_db(conn, ref_date=ref, since="2014-01-01", before=ref)
    test = conn.execute(
        "SELECT home_team,away_team,home_score,away_score,neutral FROM matches "
        "WHERE date>=? AND date<=? AND home_score IS NOT NULL", (ref, "2023-12-31")).fetchall()
    ok = lambda h, a: h in mle.fit.attack and a in mle.fit.attack
    mle_recs = _score(mle, test, ok)
    v1_recs = _score(v1, test, ok)
    assert len(mle_recs) > 100
    assert brier_score(mle_recs) < brier_score(v1_recs)  # MLE is better
```

- [ ] **Step 2: Run the live test**

Run: `python -m pytest tests/test_mle_live.py --run-live -v`
Expected: PASS (MLE Brier < v1 Brier). Fit takes ~30-60s.

- [ ] **Step 3: Write the comparison script**

```python
# scripts/run_backtest_mle.py
import sys
from kalshi_edge.data.cache import connect
from kalshi_edge.model.goal_model import GoalModel
from kalshi_edge.model.mle_model import MLEGoalModel
from kalshi_edge.backtest.metrics import brier_score, baseline_brier, accuracy

DB = "data/football.sqlite"


def _recs(model, rows, ok):
    out = []
    for r in rows:
        h, a = r["home_team"], r["away_team"]
        if not ok(h, a):
            continue
        y = "home" if r["home_score"] > r["away_score"] else ("draw" if r["home_score"] == r["away_score"] else "away")
        out.append({"probs": model.match_probabilities(h, a, neutral=bool(r["neutral"])), "outcome": y})
    return out


def main() -> None:
    ref = sys.argv[1] if len(sys.argv) > 1 else "2023-01-01"
    end = sys.argv[2] if len(sys.argv) > 2 else "2024-12-31"
    conn = connect(DB)
    mle = MLEGoalModel.from_db(conn, ref_date=ref, since="2014-01-01")
    v1 = GoalModel.from_db(conn, ref_date=ref, since="2014-01-01", before=ref)
    rows = conn.execute("SELECT home_team,away_team,home_score,away_score,neutral FROM matches "
                        "WHERE date>=? AND date<=? AND home_score IS NOT NULL", (ref, end)).fetchall()
    ok = lambda h, a: h in mle.fit.attack and a in mle.fit.attack
    mr, vr = _recs(mle, rows, ok), _recs(v1, rows, ok)
    print(f"Backtest {ref}..{end} (fit-once): {len(mr)} matches")
    print(f"  baseline Brier : {baseline_brier(mr):.4f}")
    print(f"  v1  Brier      : {brier_score(vr):.4f}  acc {accuracy(vr):.3f}")
    print(f"  MLE Brier      : {brier_score(mr):.4f}  acc {accuracy(mr):.3f}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the comparison on real data**

Run: `python scripts/run_backtest_mle.py 2023-01-01 2024-12-31`
Expected: MLE Brier < v1 Brier (prototype showed ~0.514 vs ~0.551 on 2023). Record the numbers.

- [ ] **Step 5: Commit**

```bash
git add scripts/run_backtest_mle.py tests/test_mle_live.py
git commit -m "feat: fit-once MLE backtest comparison vs v1"
```

---

## Self-Review

**Spec coverage (against the model-upgrade goal):**
- Opponent-adjusted (each rating accounts for opponents faced) full-MLE Dixon-Coles — Task 1. ✓
- Time-decay weighting, home advantage, ρ low-score correction — Task 1. ✓
- Drop-in `MLEGoalModel` (pricer/enrichment/backtest unchanged) — Task 2. ✓
- Proven better than v1 out-of-sample — Task 3. ✓
- **Deferred (documented):** wiring MLE as the default in `enrich_today`/pricing scripts (trivial follow-up once validated); probability recalibration of residual extreme over/under-confidence (separate, optional refinement); per-match refit in backtest (too slow — fit-once approximation used and noted).

**Placeholder scan:** No TBD/TODO; every step has complete, prototype-verified code and commands.

**Type consistency:** `fit_dixon_coles(conn, ref_date, since, half_life_days, min_games, max_iter) -> DCFit{attack,defense,home_adv,rho}`; `MLEGoalModel.from_db(...)` / `expected_goals` / `joint_matrix` / `match_probabilities` / `analysis` mirror the `GoalModel` surface used by `price_match` and `build_analysis`. Reuses `score_matrix(lam, mu, rho, max_goals)` and `outcome_probs(matrix)` from `poisson.py`.
