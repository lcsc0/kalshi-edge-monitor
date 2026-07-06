# SP3b — Live ticker→contract parser — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:executing-plans. Steps use checkbox (`- [ ]`) tracking.

**Goal:** Close the one gap between the finished pipeline and a real end-to-end run: turn **live Kalshi soccer events + markets** into the `games` specs that `scripts/recommend.py::build_report_data` already consumes, and give the backtest and the live surface **one** shared Kalshi-market → Pricer-contract mapping instead of two.

**Why data-driven matchup inference:** a per-match soccer *event* groups several contract *markets*. Totals/BTTS subtitles ("Over 1.5 goals scored") don't name the teams; only the moneyline legs do ("Reg Time: Argentina" / "Reg Time: Draw"). So the two teams are inferred from the event's moneyline markets — robust and observable — rather than by splitting an event-title string whose exact WC schema we can't see from the sandbox. Event-title parsing is a documented fallback.

**Architecture:** New `src/kalshi_edge/kalshi/market_parse.py` is the single source of truth:
- `ContractSpec(name, line)` and `parse_contract(series, subtitle, home, away)` — **moved here** from `backtest/replay.py`, which re-imports them (no behaviour change, no duplication).
- `Matchup(home, away, neutral)` + `infer_matchup(markets)` — teams from the moneyline legs.
- `resolve_team(name, roster)` — normalize + a small alias map (USA→United States, etc.) so Kalshi team strings resolve to the model's roster; unresolved → caller skips as *unmapped*.
- `parse_market(market, matchup)` → `ParsedMarket(ticker, contract, label)` or `None`.

`scripts/recommend.py` gains `build_games(client, conn, ...)`: group today's markets by `event_ticker`, infer the matchup, resolve teams against the model roster, build a `Pricer` + analysis per game, parse each market, fetch its orderbook, and emit the spec dicts. `main()` wires it live (still `live`-gated for network).

**Tech:** Python 3.11+, stdlib only. Reuses SP1 client, SP2b model, SP2c pricer, SP3 engine/report.

---

## Task 1: `kalshi/market_parse.py` (matchup + contract + resolution)
- Create `src/kalshi_edge/kalshi/market_parse.py`, `tests/test_market_parse.py`.
- Moneyline/total/BTTS/team-total/correct-score map to Pricer legs; spreads & player-goals → `None` (unmapped).
- `infer_matchup` returns the two non-draw moneyline teams (first-seen = "home"; neutral defaults True).
- `resolve_team` handles case/spacing + aliases; returns the roster key or `None`.
- Commit: `feat: shared Kalshi market -> Pricer contract parser`.

## Task 2: Refactor `backtest/replay.py` onto the shared parser
- Replace the local `ContractSpec`/`parse_contract` with imports from `kalshi.market_parse` (re-export for its existing callers/tests). Keep all backtest tests green.
- Commit: `refactor: backtest reuses shared market parser`.

## Task 3: Wire `recommend.py`
- Add `build_games(...)`; make `main()` build the model, call `build_games`, render the report; degrade gracefully offline.
- `tests/test_recommend_live_wiring.py` drives `build_games` with a fake client + in-memory model (offline) and asserts games/specs are built and unmapped/unknown-team markets are skipped.
- Commit: `feat: recommend.py builds live games via the market parser`.

## Self-Review
- Spec §4.4 pricer contract coverage (moneyline/totals/BTTS/team-total/score) ↔ `parse_contract`. Spreads/player-goals deferred (not on the Pricer surface). ✓
- No duplicate parsing logic (§DRY): one implementation, backtest re-imports. ✓
- Team-name mismatch handled (resolution + skip) rather than crashing or mispricing. ✓
