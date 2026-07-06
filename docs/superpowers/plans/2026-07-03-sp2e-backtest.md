# SP2e — Backtest / validation harness — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the validation harness (design §4 component 8) that decides whether the Dixon-Coles goal model actually captures real edge on Kalshi soccer markets. It reconstructs — **without lookahead** — what the model would have priced at a pre-close time for historical settled markets, then measures **calibration**, **hit-rate by edge bucket**, and **simulated fractional-Kelly P&L**. This is "the gate that clears the UNVALIDATED banner" (§9).

**Architecture:** New `kalshi_edge/backtest/` subpackage, stdlib only.
- `replay.py` — reconstructs a `BacktestSignal` per historical market with strict no-leakage guards. Builds `GoalModel.from_db(ref_date=..., since=...)` using only pre-match data, prices the mapped contract with `Pricer`, and reads the market's pre-close price from candlesticks. A best-effort `parse_contract` maps a Kalshi soccer market (series + subtitle) to a `Pricer` leg; unmappable types are recorded as `None`.
- `metrics.py` — pure functions over a list of `BacktestSignal`: calibration table + scalar error + Brier; hit-rate by edge bucket with realized-vs-implied "lift"; and a chronological fractional-Kelly P&L walk with §3 hard caps plus a flat-stake baseline.
- `harness.py` — `run_backtest(signals) -> BacktestReport` (calibration + edge buckets + P&L + a single `has_edge` verdict) and `render_report` (text/markdown).
- `scripts/run_backtest.py` — `live`-gated entrypoint pulling real Kalshi history; degrades gracefully when unreachable.

**Tech Stack:** Python 3.11+, stdlib only (no numpy). Reuses `kalshi_edge/model/goal_model.py`, `kalshi_edge/pricer/pricer.py`, `kalshi_edge/kalshi/client.py`, `kalshi_edge/data/*`. Any de-vig / edge math stays self-contained under `backtest/` (the live `edge_engine` is a parallel branch — not touched here).

**Key idea — no lookahead is everything.** A backtest that lets the model peek at the match it is pricing will always look brilliant and always lie. Two guards, both tested: (1) the model's `ref_date` must be **strictly before** the match's kickoff date (a same-day result would leak, since `decay_weight` gives a zero-age match full weight); (2) the pre-close price timestamp must be **strictly before** kickoff. Violations raise `LookaheadError`.

---

## File Structure

```
src/kalshi_edge/backtest/
  __init__.py
  replay.py     # LookaheadError, ContractSpec, HistoricalMarket, BacktestSignal,
                # parse_contract, price_at_or_before, assert_no_lookahead, replay_market
  metrics.py    # calibration_table/error, brier_score, hit_rate_by_edge_bucket,
                # KellyConfig, simulate_kelly_pnl, simulate_flat_pnl
  harness.py    # BacktestReport, run_backtest, render_report
tests/
  test_backtest_replay.py
  test_backtest_metrics.py
  test_backtest_harness.py    # includes the synthetic edged-vs-no-edge validation
scripts/
  run_backtest.py             # live-gated
```

---

## Task 1: `replay.py` — no-lookahead reconstruction + contract parser

**Files:** Create `src/kalshi_edge/backtest/__init__.py` (empty), `src/kalshi_edge/backtest/replay.py`; Test `tests/test_backtest_replay.py`.

- [ ] **Step 1: Failing tests** covering:
  - `assert_no_lookahead(ref_date, kickoff)` raises `LookaheadError` when `ref_date >= kickoff.date()`, passes when strictly before.
  - `parse_contract(series, subtitle, home, away)` maps representative fixtures: moneyline `Reg Time: <team>` → `("home",)`/`("away",)`/`("draw",)`; totals `Over 1.5 goals` → `("over", 1.5)`; BTTS → `("btts",)`/`("btts_no",)`; team total → `("home_over", 1.5)`; correct score `2-1` → `("exact", (2,1))`; unmapped (spread, player goals) → `None`.
  - `price_at_or_before(candles, ts)` picks the last candle at-or-before `ts`, normalizes cents→prob, ignores later candles (no lookahead), returns `None` when nothing precedes.
  - `replay_market(...)` on a synthetic in-memory DB produces a `BacktestSignal` with `edge == model_fair - market_price` and `realized_outcome` from `settled_yes`; and **raises `LookaheadError`** when `ref_date` is on/after kickoff (the leakage test).

- [ ] **Step 2:** Run `python -m pytest tests/test_backtest_replay.py -v` → FAIL (module missing).
- [ ] **Step 3:** Implement `replay.py` (dataclasses + guards + parser + `replay_market`).
- [ ] **Step 4:** Tests pass.
- [ ] **Step 5:** Commit `feat: no-lookahead replay and Kalshi contract parser for backtest`.

## Task 2: `metrics.py` — calibration, edge buckets, Kelly P&L

**Files:** Create `src/kalshi_edge/backtest/metrics.py`; Test `tests/test_backtest_metrics.py`.

- [ ] **Step 1: Failing tests**: perfectly-calibrated signals → ~0 calibration error and matching bins; edge buckets partition signals and compute realized rate + lift; `simulate_kelly_pnl` on all-winning positive-edge signals grows bankroll and reports positive ROI; suppression of edges above `max_edge`; flat baseline present; a losing set yields negative P&L.
- [ ] **Step 2:** FAIL.
- [ ] **Step 3:** Implement pure metrics + `KellyConfig` (fraction 0.25, `max_edge` 0.15 suppression, `min_edge` 0.0, per-bet `max_stake_fraction` cap = §3 caps) + `simulate_kelly_pnl`/`simulate_flat_pnl`.
- [ ] **Step 4:** Pass.
- [ ] **Step 5:** Commit `feat: calibration, edge-bucket and fractional-Kelly P&L metrics`.

## Task 3: `harness.py` — report + verdict

**Files:** Create `src/kalshi_edge/backtest/harness.py`; Test `tests/test_backtest_harness.py`.

- [ ] **Step 1: Failing tests**: `run_backtest(signals)` returns a `BacktestReport` bundling all three metric families with a `has_edge` bool and `positive_edge_lift`; `render_report` emits a text summary containing the verdict and ROI.
- [ ] **Step 2:** FAIL. **Step 3:** Implement. **Step 4:** Pass.
- [ ] **Step 5:** Commit `feat: backtest harness report and text renderer`.

## Task 4: Synthetic validation — the harness catches a bad model

**Files:** add to `tests/test_backtest_harness.py`.

- [ ] Seeded-RNG generator building two signal sets: (a) **well-calibrated, genuinely edged** (`model_fair == true_p`, market underprices by a fixed edge, outcome ~ Bernoulli(true_p)) → assert `has_edge` True, positive-edge lift > 0, Kelly ROI > 0. (b) **no-edge** (`model_fair` random, outcome ~ Bernoulli(market_price), i.e. market efficient / model is noise) → assert `has_edge` False, |lift| small, Kelly ROI ≈ non-positive. Deterministic via fixed seed.
- [ ] Commit `test: synthetic validation proving harness distinguishes edge from noise`.

## Task 5: `scripts/run_backtest.py` — live entrypoint

**Files:** Create `scripts/run_backtest.py`; smoke-import test in `tests/test_backtest_harness.py`.

- [ ] Pull historical soccer markets + candlesticks + settlement, build signals, run harness, print report. Wrap network in try/except → clear "historical data unreachable" message. Live path exercised only under `--run-live`.
- [ ] Commit `feat: live-gated run_backtest entrypoint`.

---

## Self-Review

**Spec coverage (§4 component 8):**
- Pull historical settled markets + candlesticks + settlement — `scripts/run_backtest.py` via `KalshiClient.get_historical_markets` / `get_historical_candlesticks` / `get_market`. ✓
- Reconstruct model's pre-close view without lookahead — `replay_market` + `assert_no_lookahead` (two strict guards, both tested). ✓
- Calibration — `calibration_table` + `calibration_error` + `brier_score`. ✓
- Hit-rate by edge bucket — `hit_rate_by_edge_bucket` with realized-vs-implied lift. ✓
- Simulated fractional-Kelly P&L — `simulate_kelly_pnl` + flat baseline. ✓
- Clears the UNVALIDATED banner — `BacktestReport.has_edge` verdict. ✓

**§3 guardrails honored in the P&L sim:** fractional Kelly (default 1/4), absurd-edge suppression (`max_edge` 0.15), per-bet exposure cap (`max_stake_fraction`). De-vig/edge math kept self-contained under `backtest/`.

**Deferred (documented, not gaps):** player-props & spread market mapping (need per-player rate / spread predicate outside SP2c Pricer surface) → recorded as unmapped; live end-to-end run depends on Kalshi historical reachability in-sandbox (validated instead by the synthetic Task-4 test).
