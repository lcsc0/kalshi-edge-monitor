# SP3 — Recommendation Surface (edge engine + combos + sizing + report) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the SP2c `Pricer`'s fair contract probabilities plus SP1's live Kalshi
order books into the **headless recommendation surface** (design §4 components 5 `edge_engine`,
6 `combo_optimizer`, 7 `sizing`, and 9 `report`+`alerts`). No web server, no order placement.
The surface is read-only text/markdown, run on demand, and it enforces every §3 guardrail so
it is hard to act on nonsense.

**Architecture:** Three new subpackages, each single-purpose and pure where possible.

- `kalshi_edge/edge/` — `devig.py` (remove overround from Kalshi prices), `engine.py`
  (`EdgeEngine` → `EdgeSignal` with the §3 guardrails), `sizing.py` (fractional Kelly + hard
  caps), `signal_log.py` (forward signal log, §3, persisted in the SP2a SQLite cache).
- `kalshi_edge/combo/` — `optimizer.py` (search eligible legs to maximise payout multiplier
  s.t. joint hit-prob ≥ target; same-game correlation via `Pricer.same_game_combo`; totals
  safety-shift).
- `kalshi_edge/report/` — `report.py` (pure data→markdown, persistent banner + per-signal
  analysis record), `alerts.py` (threshold-cross interface stub, no real push service).
- `scripts/recommend.py` — thin entrypoint wiring model → pricer → edge → combo → report.

**Tech Stack:** Python 3.11+, **stdlib only** (matches the model/pricer; no numpy). Reuses
SP1 `kalshi_edge/kalshi/orderbook.py` (`effective_prices`, `simulate_buy_yes/no`), SP2c
`kalshi_edge/pricer/` (`Pricer`), SP2b `kalshi_edge/model/goal_model.py` (`GoalModel.analysis`),
SP2a `kalshi_edge/data/cache.py` (`connect`). Tests via the SP1 pytest config.

**Key ideas:**
- Kalshi prices already *are* probabilities (dollars 0..1). A market whose N contracts
  partition the outcome space sums to `1 + overround`; **de-vig = proportional normalisation**.
  A lone binary market has no partition to normalise — its mid *is* the implied prob (the only
  "vig" is the bid/ask spread, which we do not add back).
- `edge = model_fair − market_implied`. A signal is emitted only if it survives, in order:
  **staleness** (data age ≤ max), **absurd-edge suppression** (`|edge| ≤ threshold`), and the
  **liquidity gate** (order book fills intended size within a slippage bound). Every field,
  including the model's `analysis` record (§3a), rides on the `EdgeSignal`.
- Sizing is **fractional Kelly** `(p − price)/(1 − price) × fraction`, never full, clamped ≥ 0,
  then floored by per-combo / per-game / per-day exposure caps.
- Combos: group legs by game, price same-game legs with the joint matrix (`same_game_combo`),
  multiply across independent games (`combo_across_games`); a totals leg on a high-variance
  boundary is shifted to the safer bucket before the search.

---

## File Structure

```
src/kalshi_edge/edge/
  __init__.py
  devig.py         # devig(prices), devig_single(mid)                     (pure)
  engine.py        # EdgeEngine, EdgeSignal + §3 guardrails
  sizing.py        # kelly_fraction, fractional_kelly, size_bet           (pure)
  signal_log.py    # ensure_table, log_signal, realized_hit_rate (SQLite)
src/kalshi_edge/combo/
  __init__.py
  optimizer.py     # ComboLeg, Combo, optimize, safety_shift             (pure)
src/kalshi_edge/report/
  __init__.py
  report.py        # render_report(data) -> str                          (pure)
  alerts.py        # Alert, should_alert, format_alert, push (stub)
scripts/
  recommend.py     # model -> pricer -> edge -> combo -> report entrypoint
tests/
  test_devig.py test_edge_engine.py test_sizing.py
  test_combo_optimizer.py test_report.py test_alerts.py test_signal_log.py
```

---

## Task 1: De-vig (remove Kalshi overround)

**Files:** Create `src/kalshi_edge/edge/__init__.py` (empty), `src/kalshi_edge/edge/devig.py`;
Test `tests/test_devig.py`.

- [ ] **Step 1 — failing tests:** partition of {home,draw,away} priced 0.50/0.30/0.40 (sum 1.20)
  de-vigs to proportional shares summing to 1.0 with `home` still largest; a fair partition
  (already sums to 1) is unchanged; `devig_single(0.62)` returns 0.62; empty / non-positive
  sum raises `ValueError`.
- [ ] **Step 2 — run, expect FAIL** (`ModuleNotFoundError`).
- [ ] **Step 3 — code:** `devig(prices)` = `{k: v/total}` with `total = sum(values)`, raise on
  `total <= 0`; `devig_single(mid)` returns `mid` with a docstring explaining the lone-market
  case.
- [ ] **Step 4 — run, expect PASS.**
- [ ] **Step 5 — commit:** `feat: de-vig Kalshi overround by proportional normalization`.

## Task 2: Edge engine + guardrails

**Files:** Create `src/kalshi_edge/edge/engine.py`; Test `tests/test_edge_engine.py`.

- [ ] **Step 1 — failing tests:** a healthy market (deep book, fresh, edge 0.06) → `EdgeSignal`
  not suppressed, `side="yes"` when `model_fair > market_implied`, carries the `analysis` dict;
  `|edge| > 0.15` → suppressed, reason `"absurd_edge"`; thin book that cannot fill intended
  size (or exceeds max slippage) → suppressed `"illiquid"`; `fetched_at` older than max age →
  suppressed `"stale"`; a de-vigged full partition can be passed as `market_prices` and the
  matching contract's implied prob is used.
- [ ] **Step 2 — run, expect FAIL.**
- [ ] **Step 3 — code:** `EdgeSignal` dataclass (ticker, side, model_fair, market_implied,
  edge, fillable_size, slippage, suppressed, suppression_reason, analysis). `EdgeEngine(
  absurd_edge=0.15, max_slippage=0.02, max_age_seconds=900)`; `evaluate(ticker, model_fair,
  orderbook, analysis, fetched_at, intended_size, now=None, market_prices=None, contract_key=None)`.
  Compute `market_implied` from `market_prices` (devig then pick `contract_key`) else
  `effective_prices(ob).yes_mid`; `edge = model_fair − market_implied`; `side = "yes" if edge>0
  else "no"`; gate order staleness → absurd → liquidity (`simulate_buy_yes/no`), first failure
  wins, `suppressed=True`.
- [ ] **Step 4 — run, expect PASS.**
- [ ] **Step 5 — commit:** `feat: edge engine with staleness, absurd-edge and liquidity gates`.

## Task 3: Fractional-Kelly sizing + hard caps

**Files:** Create `src/kalshi_edge/edge/sizing.py`; Test `tests/test_sizing.py`.

- [ ] **Step 1 — failing tests:** `kelly_fraction(0.6, 0.5) == (0.6−0.5)/(1−0.5) == 0.2`;
  `fractional_kelly` at 0.25 is a quarter of full and strictly `< kelly_fraction`; negative
  edge clamps to 0; `size_bet` applies the fraction to bankroll then floors by the tightest of
  per-combo / (per-game − game_exposure) / (per-day − day_exposure) caps; an exhausted daily
  budget yields 0.
- [ ] **Step 2 — run, expect FAIL.**
- [ ] **Step 3 — code:** `kelly_fraction(p, price)=max(0,(p−price)/(1−price))`;
  `fractional_kelly(p, price, fraction=0.25)=fraction*kelly_fraction`; `size_bet(p, price,
  bankroll, *, fraction, per_combo_cap, per_game_cap, per_day_cap, game_exposure, day_exposure)`.
- [ ] **Step 4 — run, expect PASS.**
- [ ] **Step 5 — commit:** `feat: fractional-Kelly sizing with per-combo/game/day caps`.

## Task 4: Combo optimizer + totals safety-shift

**Files:** Create `src/kalshi_edge/combo/__init__.py` (empty), `src/kalshi_edge/combo/optimizer.py`;
Test `tests/test_combo_optimizer.py`.

- [ ] **Step 1 — failing tests:** legs across two games — `optimize` returns the max-multiplier
  combo whose model joint-prob ≥ target and rejects combos below target; a same-game pair is
  priced by `same_game_combo` (≠ marginal product); a leg with edge ≤ 0 is refused; `safety_shift`
  turns `("under", 2.5)` on a high-variance boundary into `("under", 3.5)` and the shifted bucket
  has the higher (safer) model prob; `max_legs` bounds the search.
- [ ] **Step 2 — run, expect FAIL.**
- [ ] **Step 3 — code:** `ComboLeg(game_id, pricer, leg, model_fair, market_price, edge)`;
  `Combo(legs, joint_prob, multiplier)`; `joint_prob` groups by `game_id` → `same_game_combo`
  per game → product across games; `multiplier = Π 1/market_price`; `optimize(legs, target_prob,
  max_legs=4)` searches `itertools.combinations` sizes 1..max_legs over legs with `edge>0`,
  keeps the feasible max-multiplier combo; `safety_shift(leg, pricer, window, step)` shifts a
  boundary totals leg to the safer bucket.
- [ ] **Step 4 — run, expect PASS.**
- [ ] **Step 5 — commit:** `feat: combo optimizer with joint-prob target and totals safety-shift`.

## Task 5: Forward signal log

**Files:** Create `src/kalshi_edge/edge/signal_log.py`; Test `tests/test_signal_log.py`.

- [ ] **Step 1 — failing tests:** `ensure_table` creates `signal_log`; `log_signal` persists an
  `EdgeSignal` with inputs + timestamps; `realized_hit_rate` accrues from rows once outcomes are
  set. Reuses `cache.connect()` — no edit to `cache.py`.
- [ ] **Step 2 — run, expect FAIL.**
- [ ] **Step 3 — code:** table `signal_log(ticker, side, model_fair, market_implied, edge,
  fillable_size, slippage, suppressed, suppression_reason, fetched_at, logged_at, outcome)`;
  helpers to insert and to compute realized hit-rate over settled rows.
- [ ] **Step 4 — run, expect PASS.**
- [ ] **Step 5 — commit:** `feat: forward signal log persisted in the SQLite cache`.

## Task 6: Report + alerts

**Files:** Create `src/kalshi_edge/report/__init__.py` (empty), `report.py`, `alerts.py`;
Tests `tests/test_report.py`, `tests/test_alerts.py`.

- [ ] **Step 1 — failing tests:** `render_report` output starts with the persistent banner
  `UNVALIDATED MODEL — TRADE SMALL` (until `validated=True`); shows per-market model-fair vs
  Kalshi de-vigged with edge; each flagged signal includes its analysis drivers (expected goals,
  strengths, outcome probs) — never a bare edge number; suggested combos show fractional-Kelly
  sizing. `alerts.should_alert` fires on threshold cross; `push` is an interface-only stub.
- [ ] **Step 2 — run, expect FAIL.**
- [ ] **Step 3 — code:** `render_report(data)` pure function; `alerts.Alert`, `should_alert`,
  `format_alert`, `push` (raises/no-ops as a documented stub).
- [ ] **Step 4 — run, expect PASS.**
- [ ] **Step 5 — commit:** `feat: headless markdown report with banner, analysis drivers, alerts stub`.

## Task 7: Entrypoint

**Files:** Create `scripts/recommend.py`.

- [ ] Wire `GoalModel.from_db` → `Pricer.from_model` → `EdgeEngine` → `optimize` → `render_report`,
  reading live orderbooks via SP1 when run with real data; importable `build_report(...)` core so
  it is smoke-testable offline. Commit: `feat: recommend.py entrypoint wiring the surface`.

---

## Self-Review

**Spec coverage:**
- §3 Fractional Kelly (never full) — `fractional_kelly`/`size_bet`; test asserts `<` full. ✓
- §3 Hard caps (per-combo/game/day) — `size_bet` floors by the tightest remaining cap. ✓
- §3 Absurd-edge suppression — `EdgeEngine` reason `"absurd_edge"`. ✓
- §3 Liquidity gate — `simulate_buy_yes/no`, size + slippage bound, reason `"illiquid"`. ✓
- §3 Staleness gate — `fetched_at` age vs `max_age_seconds`, reason `"stale"`. ✓
- §3 Persistent banner — `render_report` emits it until `validated=True`. ✓
- §3 Forward signal log — `signal_log` in the SQLite cache. ✓
- §3a Grounding — `EdgeSignal.analysis` carried through and rendered per signal. ✓
- §4.5 edge_engine — de-vig + edge + gates. ✓
- §4.6 combo_optimizer — max multiplier s.t. joint-prob target; same-game via joint matrix;
  positive edge required; totals safety-shift. ✓
- §4.7 sizing — fractional Kelly + caps. ✓
- §9 report+alerts — headless markdown, per-signal analysis, alerts stub, no web server. ✓
- **Deferred (documented):** real push transport in `alerts.py` (interface only — no service in
  scope); live WebSocket wiring in `recommend.py` (SP1 provides REST; core is offline-testable).

**Type consistency:** `devig(dict)->dict`, `EdgeEngine.evaluate(...)->EdgeSignal`, sizing floats,
`optimize(list[ComboLeg], float)->Combo|None`, `render_report(dict)->str` — consistent across
tasks and tests. Legs stay `(name,)`/`(name, line)` tuples, matching the pricer.
