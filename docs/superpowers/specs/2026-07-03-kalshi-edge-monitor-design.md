# Kalshi Edge Monitor — Design

**Date:** 2026-07-03
**Status:** Approved (pending user review of this doc)
**Scope of this doc:** The read-only, monitor-only edge monitor for soccer. Auto-execution
is explicitly out of scope and deferred to a later, separately-specced phase.

---

## 1. Purpose

Give the operator consistent **daily recommendations** for FIFA World Cup 2026 (and future
soccer) markets on Kalshi:

- An **independent** fair-value estimate per contract (bivariate-Poisson goal model), so
  "edge vs Kalshi" is real and not circular.
- **Edge flags** where Kalshi's de-vigged price diverges from model fair value and there is
  enough order-book depth to fill intended size.
- **Combo suggestions** that maximize payout multiplier for a target joint hit-probability,
  pricing same-game correlation correctly and applying a totals safety-shift preference.
- **Fractional-Kelly sizing** with hard caps.

The operator reads the dashboard and **places every trade manually.** The system never sends
an order in this phase.

## 2. Non-goals (this phase)

- No order placement / execution of any kind. No Kalshi order endpoints are wired.
- No tournament / advancement / futures markets — today's per-match markets only.
- No sports other than soccer (model interface is pluggable so others can be added later).
- No xG pipeline (no reliable free xG for national teams; results/Elo based instead).

## 3. Hard constraints & guardrails

The model will be **unvalidated until the backtest passes**, and even then thin. The system
must make it hard to act on nonsense:

- **Fractional Kelly** (default 1/4) on all sizing; never full Kelly.
- **Hard caps:** per-combo, per-game, and per-day exposure ceilings (config).
- **Absurd-edge suppression:** if model edge on a leg exceeds a threshold (e.g. > 15pp), it
  is treated as a probable model/data error and **suppressed**, not sized up.
- **Liquidity gate:** a signal is only shown if order-book depth can fill intended size
  within a max-slippage bound.
- **Staleness gates:** the pricer refuses to emit fair prices from data older than a max age;
  every data source carries an age flag.
- **Persistent banner:** "UNVALIDATED MODEL — TRADE SMALL" until the backtest is green.
- **Forward signal log:** every emitted signal is persisted with its inputs so realized
  hit-rate accrues from day one.

## 4. Components

Each component is isolated, single-purpose, and independently testable.

1. **`kalshi_client`** — read-only REST + WebSocket wrapper.
   - `GET /markets` filtered by soccer `series_ticker` / `event_ticker` and today's window.
   - `GET /markets/{ticker}/orderbook` → reconstruct **effective bid/ask/mid/depth** from the
     yes-bid/no-bid representation (Kalshi returns only yes-bids and no-bids; a no-bid at `p`
     is the effective yes-ask at `1 - p`).
   - `GET /historical/markets` + `/historical/markets/{ticker}/candlesticks` for the backtest.
   - WebSocket subscription for live price updates.
   - **Contains no order endpoints.**

2. **`data_sources`** — free football data behind one interface, cached locally with age flags:
   - Historical international match results (public dataset) — for the Dixon-Coles fit.
   - World Football Elo ratings — strength prior.
   - football-data.org (free tier) — recent WC fixtures/results/schedule.
   - FBref goals-per-90 — for player-props (key strikers) only.
   - Scrapers/fetchers isolated behind a common `Source` interface; each caches to SQLite and
     exposes a `fetched_at` timestamp.

3. **`goal_model`** — Dixon-Coles bivariate Poisson.
   - Fit team attack/defense strengths + home advantage from results, blended with the Elo
     prior for teams with sparse data.
   - Output: per-match **joint** score matrix `P(home_goals, away_goals)`.
   - Manual-override hook (adjust a team's expected goals for lineup/injury/motivation news).
   - Behind a `GoalModel` interface so alternative sports/models can be swapped in.

4. **`pricer`** — joint matrix → fair probability per Kalshi contract type:
   - Moneyline (regulation), totals buckets, both-teams-to-score, squad goals, player-scores.
   - Same-game combos priced by summing over the joint matrix (not multiplying marginals).
   - Player props via a per-player scoring rate derived from goals-per-90 and match share.

5. **`edge_engine`** — per live market: model fair prob vs Kalshi de-vigged price → edge.
   - Applies the liquidity gate and absurd-edge suppression.

6. **`combo_optimizer`** — search today's eligible legs to **maximize payout multiplier**
   subject to **joint hit-probability ≥ target** ("smallest risk" knob):
   - Respects same-game correlation via the joint matrix.
   - Requires positive model edge on every leg.
   - Applies the **totals safety-shift**: when a totals leg sits on a high-variance boundary,
     auto-prefer the safer bucket (e.g. under-2.5 → under-3.5) per config policy.

7. **`sizing`** — fractional Kelly on legs and combos; enforces the hard caps.

8. **`backtest`** — validation harness:
   - Pull historical settled soccer markets + their candlesticks + settlement outcomes.
   - Reconstruct what the model would have said at a chosen pre-close time.
   - Measure whether flagged edges settled in-the-money at the implied rate (calibration,
     hit-rate by edge bucket, simulated fractional-Kelly P&L).
   - **This is the gate that clears the "UNVALIDATED" banner.**

9. **`report` + `alerts`** — headless text output, no web UI:
   - A plain-text/markdown recommendation report: today's games; per-market fair vs Kalshi;
     flagged edges; suggested combos with sizing. Designed to be run on demand and read back
     to the operator from a phone via Claude remote control / dispatch.
   - Optional push alert on threshold cross.
   - Read-only surface; operator trades manually. **No dashboard / web server.**

## 5. Data flow

```
free data (results/Elo/fixtures/FBref)
        │  (fit daily)
        ▼
   goal_model ──► pricer ──► fair prices (today's games)
                                   │
kalshi_client (live prices+depth) ─┤
                                   ▼
                             edge_engine ──► combo_optimizer ──► sizing
                                   │                                │
                                   └──────────────► dashboard / alerts ──► operator trades
```

Backtest runs offline over historical Kalshi data + historical results to validate before
any of the above is trusted.

## 6. Storage

Local **SQLite**: cached source data + `fetched_at`, fitted model params, the forward signal
log, and backtest results. Chosen for zero-setup and easy inspection.

## 7. Error handling

- Each data source degrades to stale cache with a visible age flag; pricer refuses if too old.
- `kalshi_client` retries with backoff; surfaces API/WebSocket disconnects on the dashboard.
- `edge_engine` hard-suppresses on missing liquidity or absurd edge rather than showing a
  tempting-but-wrong signal.

## 8. Tech

Python. `httpx` + `websockets` (Kalshi), `numpy`/`scipy`/`pandas` (model & backtest),
`sqlite3`. Output is a headless text/markdown report (no web server) — invoked from a phone
via Claude remote control / dispatch.

## 9. Decomposition & build order

Three sub-projects, each its own spec → plan → implementation cycle:

- **SP1 — Kalshi read-only client + market puller.** Enumerate today's soccer markets,
  reconstruct effective prices/depth, pull historical data for the backtest. Verifiable
  directly against the live API. *(Built first — dependency of everything.)*
- **SP2 — data_sources + goal_model + pricer + backtest.** Independent fair prices for
  today's games, validated by the backtest harness.
- **SP3 — edge_engine + combo_optimizer + sizing + text report/alerts.** The headless
  recommendation surface, run on demand from a phone via Claude remote control / dispatch.

Future (separate, out of scope here): **SP4 — auto-execution**, gated behind a green backtest
and a paper-trading period, disabled by default behind a hard flag.
