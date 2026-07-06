# SP2e — Model Calibration Backtest — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Measure whether the goal model has real skill by walking it forward over thousands of historical international matches (built strictly from prior data — no lookahead) and scoring its probabilities: Brier, log-loss, accuracy, calibration table, all vs a climatology baseline. This is the number we optimize the model against.

**Architecture:** Add a `before` (as-of) cutoff to `team_strengths`/`GoalModel.from_db` so a match can be predicted using only earlier data. A pure `metrics.py` scores prediction records. A `backtest.py` walk-forward driver builds an as-of model per match and collects records. A `run_backtest.py` script runs it on the real DB and prints the report.

**Tech Stack:** Python 3.11+, stdlib only. Builds on SP2a (`data/`) and SP2b (`model/`). SP1 pytest config.

**Record shape:** `{"date": str, "probs": {"home","draw","away"}, "outcome": "home"|"draw"|"away"}`.

---

## File Structure

```
src/kalshi_edge/backtest/
  __init__.py
  metrics.py     # brier_score, log_loss, accuracy, baseline_brier, calibration_table
  runner.py      # backtest_outcomes(conn, ...) walk-forward
scripts/
  run_backtest.py
tests/
  test_metrics.py
  test_backtest_runner.py
  test_backtest_live.py   # marked 'live'
```

Also modifies: `src/kalshi_edge/model/strengths.py` and `src/kalshi_edge/model/goal_model.py` (add `before` cutoff).

---

## Task 1: As-of cutoff (prevent lookahead)

**Files:**
- Modify: `src/kalshi_edge/model/strengths.py`
- Modify: `src/kalshi_edge/model/goal_model.py`
- Test: `tests/test_strengths.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_strengths.py (append)
def test_before_cutoff_excludes_later_matches():
    rows = "date,home_team,away_team,home_score,away_score,tournament,city,country,neutral\n"
    rows += "2020-01-01,A,B,5,0,Friendly,X,Y,TRUE\n"   # before cutoff
    rows += "2025-01-01,A,B,0,5,Friendly,X,Y,TRUE\n"   # after cutoff (must be ignored)
    conn = connect(); load_results_csv(conn, rows)
    s = team_strengths(conn, ref_date="2021-01-01", before="2021-01-01")
    # Only the 5-0 match counts, so A's attack must exceed its defense.
    assert s["teams"]["A"]["attack"] > s["teams"]["A"]["defense"]
```

- [ ] **Step 2: Run it to verify it fails**

Run: `python -m pytest tests/test_strengths.py::test_before_cutoff_excludes_later_matches -v`
Expected: FAIL — `team_strengths() got an unexpected keyword argument 'before'`

- [ ] **Step 3: Add the `before` cutoff**

In `src/kalshi_edge/model/strengths.py`, change the `team_strengths` signature and query:

```python
def team_strengths(conn, ref_date: str,
                   half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
                   since: str | None = None,
                   before: str | None = None) -> dict:
```

and immediately after the existing `if since:` block, add:

```python
    if before:
        query += " AND date < ?"
        args.append(before)
```

In `src/kalshi_edge/model/goal_model.py`, thread it through `from_db`:

```python
    @classmethod
    def from_db(cls, conn, ref_date: str, half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
                since: str | None = None, before: str | None = None,
                rho: float = 0.0, max_goals: int = 10) -> "GoalModel":
        s = team_strengths(conn, ref_date, half_life_days, since, before)
        return cls(s["mu"], s["home_factor"], s["teams"], rho=rho, max_goals=max_goals)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_strengths.py -v`
Expected: PASS (all, including the new one)

- [ ] **Step 5: Commit**

```bash
git add src/kalshi_edge/model/strengths.py src/kalshi_edge/model/goal_model.py tests/test_strengths.py
git commit -m "feat: as-of before cutoff to prevent backtest lookahead"
```

---

## Task 2: Scoring metrics

**Files:**
- Create: `src/kalshi_edge/backtest/__init__.py` (empty), `src/kalshi_edge/backtest/metrics.py`
- Test: `tests/test_metrics.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_metrics.py
from kalshi_edge.backtest.metrics import (
    brier_score, log_loss, accuracy, baseline_brier, calibration_table,
)

PERFECT = [{"date": "d", "probs": {"home": 1.0, "draw": 0.0, "away": 0.0}, "outcome": "home"}]
RECORDS = [
    {"date": "d", "probs": {"home": 0.6, "draw": 0.3, "away": 0.1}, "outcome": "home"},
    {"date": "d", "probs": {"home": 0.2, "draw": 0.3, "away": 0.5}, "outcome": "away"},
    {"date": "d", "probs": {"home": 0.3, "draw": 0.4, "away": 0.3}, "outcome": "draw"},
]


def test_brier_zero_for_perfect_prediction():
    assert brier_score(PERFECT) == 0.0


def test_brier_and_logloss_positive_for_imperfect():
    assert brier_score(RECORDS) > 0.0
    assert log_loss(RECORDS) > 0.0


def test_accuracy_counts_argmax_hits():
    # record1 argmax=home✓, record2 argmax=away✓, record3 argmax=draw✓ -> 1.0
    assert accuracy(RECORDS) == 1.0


def test_model_beats_baseline_when_it_has_signal():
    # RECORDS predicts each actual outcome as its argmax -> should beat climatology
    assert brier_score(RECORDS) < baseline_brier(RECORDS)


def test_calibration_table_bins_and_reports_frequency():
    recs = [{"date": "d", "probs": {"home": 0.85, "draw": 0.1, "away": 0.05},
             "outcome": "home" if i < 8 else "away"} for i in range(10)]
    table = calibration_table(recs, outcome="home", bins=10)
    top = [row for row in table if row["bin"][0] <= 0.85 < row["bin"][1] or row["bin"][1] == 1.0][-1]
    assert top["n"] == 10 and round(top["observed"], 2) == 0.80
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_metrics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kalshi_edge.backtest.metrics'`

- [ ] **Step 3: Write the metrics**

```python
# src/kalshi_edge/backtest/metrics.py
import math
from collections import Counter

OUTCOMES = ("home", "draw", "away")


def brier_score(records: list[dict]) -> float:
    if not records:
        return 0.0
    total = 0.0
    for r in records:
        p, y = r["probs"], r["outcome"]
        total += sum((p[k] - (1.0 if k == y else 0.0)) ** 2 for k in OUTCOMES)
    return total / len(records)


def log_loss(records: list[dict], eps: float = 1e-15) -> float:
    if not records:
        return 0.0
    total = 0.0
    for r in records:
        p = min(max(r["probs"][r["outcome"]], eps), 1 - eps)
        total += -math.log(p)
    return total / len(records)


def accuracy(records: list[dict]) -> float:
    if not records:
        return 0.0
    hits = sum(1 for r in records if max(r["probs"], key=r["probs"].get) == r["outcome"])
    return hits / len(records)


def baseline_brier(records: list[dict]) -> float:
    """Climatology baseline: predict the overall outcome frequencies for every match."""
    if not records:
        return 0.0
    counts = Counter(r["outcome"] for r in records)
    n = len(records)
    base = {k: counts.get(k, 0) / n for k in OUTCOMES}
    total = 0.0
    for r in records:
        y = r["outcome"]
        total += sum((base[k] - (1.0 if k == y else 0.0)) ** 2 for k in OUTCOMES)
    return total / len(records)


def calibration_table(records: list[dict], outcome: str = "home", bins: int = 10) -> list[dict]:
    """Reliability table for a single outcome's predicted probability."""
    table = []
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        if b == bins - 1:
            sel = [r for r in records if lo <= r["probs"][outcome] <= hi]
        else:
            sel = [r for r in records if lo <= r["probs"][outcome] < hi]
        if not sel:
            continue
        avg_pred = sum(r["probs"][outcome] for r in sel) / len(sel)
        observed = sum(1 for r in sel if r["outcome"] == outcome) / len(sel)
        table.append({"bin": (lo, hi), "n": len(sel), "avg_pred": avg_pred, "observed": observed})
    return table
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_metrics.py -v`
Expected: PASS (5)

- [ ] **Step 5: Commit**

```bash
git add src/kalshi_edge/backtest/__init__.py src/kalshi_edge/backtest/metrics.py tests/test_metrics.py
git commit -m "feat: backtest scoring metrics"
```

---

## Task 3: Walk-forward backtest driver

**Files:**
- Create: `src/kalshi_edge/backtest/runner.py`
- Test: `tests/test_backtest_runner.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_backtest_runner.py
from kalshi_edge.data.cache import connect
from kalshi_edge.data.intl_results import load_results_csv
from kalshi_edge.backtest.runner import backtest_outcomes

# Strong beats Weak repeatedly in the training window (2020-2022), then two
# test matches in 2023 the model should confidently call for Strong.
ROWS = "date,home_team,away_team,home_score,away_score,tournament,city,country,neutral\n" + "".join(
    f"20{y}-0{m+1}-01,Strong,Weak,3,0,Friendly,X,Y,TRUE\n" for y in (20, 21, 22) for m in range(6)
) + "2023-01-10,Strong,Weak,2,0,Friendly,X,Y,TRUE\n2023-02-10,Weak,Strong,0,2,Friendly,X,Y,TRUE\n"


def test_backtest_outcomes_records_predictions_without_lookahead():
    conn = connect(); load_results_csv(conn, ROWS)
    recs = backtest_outcomes(conn, test_start="2023-01-01", test_end="2023-12-31", since="2018-01-01")
    assert len(recs) == 2
    # Both test matches were Strong wins (home then away); model should favor Strong.
    assert recs[0]["outcome"] == "home"   # 2023-01-10 Strong home win
    assert recs[1]["outcome"] == "away"   # 2023-02-10 Strong away win
    assert recs[0]["probs"]["home"] > recs[0]["probs"]["away"]  # favors Strong (home)
    assert recs[1]["probs"]["away"] > recs[1]["probs"]["home"]  # favors Strong (away)


def test_backtest_skips_matches_with_no_prior_history():
    conn = connect(); load_results_csv(conn, ROWS)
    # First-ever appearance can't be predicted; a 2019 window has no prior data.
    recs = backtest_outcomes(conn, test_start="2019-01-01", test_end="2019-12-31", since="2018-01-01")
    assert recs == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_backtest_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'kalshi_edge.backtest.runner'`

- [ ] **Step 3: Write the runner**

```python
# src/kalshi_edge/backtest/runner.py
from kalshi_edge.model.goal_model import GoalModel


def _outcome(home_score: int, away_score: int) -> str:
    if home_score > away_score:
        return "home"
    if home_score == away_score:
        return "draw"
    return "away"


def backtest_outcomes(conn, test_start: str, test_end: str,
                      since: str | None = None,
                      half_life_days: float = 730.0) -> list[dict]:
    """Walk forward over completed matches in [test_start, test_end], predicting each
    with a model built strictly from earlier data (before=match date). Returns records."""
    query = ("SELECT date, home_team, away_team, home_score, away_score, neutral "
             "FROM matches WHERE date >= ? AND date <= ? "
             "AND home_score IS NOT NULL AND away_score IS NOT NULL ORDER BY date")
    records = []
    for m in conn.execute(query, (test_start, test_end)).fetchall():
        try:
            model = GoalModel.from_db(conn, ref_date=m["date"], since=since, before=m["date"])
            probs = model.match_probabilities(m["home_team"], m["away_team"],
                                              neutral=bool(m["neutral"]))
        except (ValueError, ZeroDivisionError):
            continue  # team without prior history
        records.append({
            "date": m["date"],
            "probs": probs,
            "outcome": _outcome(m["home_score"], m["away_score"]),
        })
    return records
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_backtest_runner.py -v`
Expected: PASS (2). Then run the full suite `python -m pytest -q`.

- [ ] **Step 5: Commit**

```bash
git add src/kalshi_edge/backtest/runner.py tests/test_backtest_runner.py
git commit -m "feat: walk-forward backtest driver"
```

---

## Task 4: run_backtest script + live skill check

**Files:**
- Create: `scripts/run_backtest.py`
- Create: `tests/test_backtest_live.py`

- [ ] **Step 1: Write the live test (small window, asserts skill vs baseline)**

```python
# tests/test_backtest_live.py
import os
import pytest
from kalshi_edge.data.cache import connect
from kalshi_edge.backtest.runner import backtest_outcomes
from kalshi_edge.backtest.metrics import brier_score, baseline_brier

DB = "data/football.sqlite"


@pytest.mark.live
def test_model_has_skill_over_baseline_on_real_history():
    if not os.path.exists(DB):
        pytest.skip("run scripts/build_db.py first")
    recs = backtest_outcomes(connect(DB), test_start="2023-01-01", test_end="2023-06-30",
                             since="2015-01-01")
    assert len(recs) > 100
    # The model should beat the climatology baseline (lower Brier = better).
    assert brier_score(recs) < baseline_brier(recs)
```

- [ ] **Step 2: Run it against the real DB**

Run: `python scripts/build_db.py && python -m pytest tests/test_backtest_live.py --run-live -v`
Expected: PASS (model Brier < baseline). If it FAILS, that is a real finding — the v1 model
lacks skill on that window; record the numbers, do not fudge the assertion.

- [ ] **Step 3: Write the report script**

```python
# scripts/run_backtest.py
import sys
from kalshi_edge.data.cache import connect
from kalshi_edge.backtest.runner import backtest_outcomes
from kalshi_edge.backtest.metrics import (
    brier_score, log_loss, accuracy, baseline_brier, calibration_table,
)

DB = "data/football.sqlite"


def main() -> None:
    start = sys.argv[1] if len(sys.argv) > 1 else "2022-01-01"
    end = sys.argv[2] if len(sys.argv) > 2 else "2024-12-31"
    recs = backtest_outcomes(connect(DB), test_start=start, test_end=end, since="2014-01-01")
    print(f"Backtest {start}..{end}: {len(recs)} matches")
    print(f"  Brier        : {brier_score(recs):.4f}  (baseline {baseline_brier(recs):.4f})")
    print(f"  Log-loss     : {log_loss(recs):.4f}")
    print(f"  Accuracy     : {accuracy(recs):.3f}")
    print("  Calibration (home-win prob):")
    for row in calibration_table(recs, outcome="home", bins=10):
        lo, hi = row["bin"]
        print(f"    {lo:.1f}-{hi:.1f}  n={row['n']:<5} pred={row['avg_pred']:.3f} "
              f"observed={row['observed']:.3f}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the report on the real data**

Run: `python scripts/run_backtest.py 2022-01-01 2024-12-31`
Expected: prints Brier/log-loss/accuracy vs baseline + a calibration table. Record the numbers —
this is the model-quality benchmark future model changes must beat.

- [ ] **Step 5: Commit**

```bash
git add scripts/run_backtest.py tests/test_backtest_live.py
git commit -m "feat: run_backtest report and live skill test"
```

---

## Self-Review

**Spec coverage (against §8 backtest):**
- Reconstruct what the model would have said at a chosen past time, no lookahead — Task 1 (`before`), Task 3. ✓
- Measure calibration + hit-rate + skill vs baseline — Tasks 2, 4. ✓
- Produces the benchmark that gates model improvements — Task 4. ✓
- **Deferred (documented):** backtest against *Kalshi historical settlement prices* + simulated
  fractional-Kelly P&L — needs the pricer (SP2c) to price every contract type first; this slice
  validates the goal model against real match outcomes, the larger and cleaner dataset.

**Placeholder scan:** No TBD/TODO; every step has complete code and commands. The Task-4 live
assertion may legitimately fail (v1 model may lack skill) — that is a recorded finding, not a gap.

**Type consistency:** record shape `{"date","probs":{home,draw,away},"outcome"}` consistent across
`metrics.py`, `runner.py`, and all tests. `team_strengths(..., before=None)` and
`GoalModel.from_db(..., before=None)` threaded consistently in Task 1 and used in Task 3.
