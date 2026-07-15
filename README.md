# Kalshi Edge Monitor

A **read-only, monitor-only** edge monitor for FIFA World Cup 2026 (and future
soccer) markets on Kalshi. It produces an independent fair-value estimate per
contract from a Dixon-Coles goal model, flags where Kalshi's de-vigged price
diverges from that fair value with enough order-book depth to fill, suggests
correlation-aware combos, and sizes everything with fractional Kelly under hard
caps. **The operator reads the report and places every trade manually — the
system never sends an order.**

> ⚠️ **UNVALIDATED MODEL — TRADE SMALL.** The model is thin and unproven until
> the backtest passes on real settled markets. Every report carries this banner
> and the guardrails below are deliberately conservative.

See `docs/superpowers/specs/2026-07-03-kalshi-edge-monitor-design.md` for the
full design.

## What it does

```
free football data (results / goalscorers)          Kalshi live prices + depth
        │  fit daily + per-game context                        │
        ▼                                                      │
   goal_model ──► pricer ──► fair prices + analysis record     │
                                   │                           │
                                   └────► edge_engine ◄─────────┘
                                            │
                              combo_optimizer ──► sizing ──► report ──► operator
```

The backtest runs offline over historical Kalshi data + results to validate the
model before any of it is trusted.

## Components

| Package | Role |
|---|---|
| `kalshi_edge.kalshi` | Read-only Kalshi REST client, order-book reconstruction (effective bid/ask/mid, fill/slippage), historical endpoints, live market → contract parsing. **No order endpoints.** |
| `kalshi_edge.data` | Free football sources cached to SQLite with `fetched_at` age flags (international results, goalscorers). |
| `kalshi_edge.model` | Dixon-Coles bivariate-Poisson goal model, time-decay team strengths, joint score matrix + analysis record, player-goals scoring rates. |
| `kalshi_edge.pricer` | Joint matrix → fair probability per contract type (moneyline, totals, BTTS, team totals, spread, correct score) + correlation-aware same/cross-game combos. |
| `kalshi_edge.edge` | De-vig, `EdgeEngine` (staleness / absurd-edge / liquidity gates), fractional-Kelly sizing with caps, forward signal log. |
| `kalshi_edge.combo` | Combo optimizer: maximize payout multiplier subject to a joint-hit-probability target, with the totals safety-shift. |
| `kalshi_edge.report` | Headless markdown recommendation report (banner + per-bet analysis drivers); alerts stub. |
| `kalshi_edge.backtest` | No-lookahead replay, calibration, hit-rate by edge bucket, simulated fractional-Kelly P&L, `has_edge` verdict. |

## Guardrails (why it's hard to act on nonsense)

- **Fractional Kelly** (default ¼) on all sizing — never full Kelly.
- **Hard caps** — per-combo, per-game, per-day exposure ceilings.
- **Absurd-edge suppression** — an edge above the threshold (default 15pp) is
  treated as a probable data/model error and dropped, not sized up.
- **Liquidity gate** — a signal shows only if the book can fill intended size
  within a max-slippage bound.
- **Staleness gate** — the pricer refuses to emit from data older than a max age.
- **Forward signal log** — every emitted signal is persisted so realized
  hit-rate accrues from day one.

## Install

```bash
pip install -e ".[dev]"
```

Python 3.11+. Runtime deps are stdlib + `httpx`; the model/backtest use no numpy.

## Usage

**1. Build the local football database** (international results + goalscorers):

```bash
python scripts/build_db.py        # writes data/football.sqlite
```

**2. Generate today's recommendation report:**

```bash
python scripts/recommend.py       # model → pricer → edge → combo → report
```

**3. Run the backtest** (the validation gate that clears the UNVALIDATED banner):

```bash
python scripts/run_backtest.py --run-live
```

All three degrade gracefully with a clear message when the database or the
Kalshi API is unreachable.

### Optional: confirmed lineups + coaches

The baseline needs **no API keys**. A free [API-Football](https://www.api-football.com/)
key enables confirmed lineups + coaches for the analysis record; without it the
model falls back to squad strength with a wider-uncertainty flag. Copy
`.env.example` to `.env` and paste your key — `.env` is gitignored.

## Testing

```bash
python -m pytest -q            # unit tests (network tests are skipped)
python -m pytest --run-live    # also hit the live Kalshi API / built DB
```

Tests that reach the network or a built DB are marked `@pytest.mark.live` and
skip by default.

## Status & roadmap

**Complete:** the full soccer pipeline — data → model → pricer → edge engine →
combo → report — plus the backtest harness (self-validated on synthetic data:
it correctly separates an edged model from noise). Every soccer contract family
Kalshi lists is priced.

**Open / deferred:**
- **Model validation on real data** — pending network access to Kalshi's
  historical endpoints; until then the UNVALIDATED banner stays up.
- **Lineup/coach λ enrichment** — designed to degrade gracefully; needs the
  API-Football key.
- **MLB / other sports** — the count model, pricer, and parser are
  sport-agnostic; a sport is added via data loader + config + contract parser.
- **Auto-execution** — explicitly out of scope; gated behind a green backtest
  and a paper-trading period in a separate, hard-flagged phase.
