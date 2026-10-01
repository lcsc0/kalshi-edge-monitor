from datetime import datetime, timezone

import pytest

from kalshi_edge.edge.engine import EdgeEngine
from kalshi_edge.edge.policy import DEFAULT_POLICY, StrategyPolicy, side_prob
from kalshi_edge.kalshi.models import Orderbook, OrderbookLevel
from kalshi_edge.backtest.edge_metrics import KellyConfig, simulate_kelly_pnl
from kalshi_edge.backtest.replay import BacktestSignal

NOW = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
ANALYSIS = {"home": "A", "away": "B"}


def _book(mid):
    # tight, deep book centred on `mid`
    return Orderbook(ticker="T",
                     yes=(OrderbookLevel(price=round(mid - 0.005, 3), count=1000),),
                     no=(OrderbookLevel(price=round(1 - mid - 0.005, 3), count=1000),))


def _eval(engine, fair, mid):
    return engine.evaluate(ticker="T", model_fair=fair, orderbook=_book(mid),
                           analysis=ANALYSIS, fetched_at=NOW, intended_size=100, now=NOW)


def test_policy_rejects_full_kelly_and_bad_bands():
    with pytest.raises(ValueError):
        StrategyPolicy(kelly_fraction=1.0)
    with pytest.raises(ValueError):
        StrategyPolicy(min_edge=0.2, max_edge=0.1)
    assert DEFAULT_POLICY.allow_combos is False


def test_side_prob():
    assert side_prob(0.7, "yes") == 0.7
    assert abs(side_prob(0.7, "no") - 0.3) < 1e-12


def test_engine_from_policy_enforces_edge_band():
    eng = EdgeEngine.from_policy(DEFAULT_POLICY)
    assert _eval(eng, 0.52, 0.50).suppression_reason == "below_min_edge"   # 2pp
    assert _eval(eng, 0.55, 0.50).suppressed is False                      # 5pp, in band
    assert _eval(eng, 0.65, 0.50).suppression_reason == "absurd_edge"      # 15pp


def test_engine_from_policy_enforces_probability_band():
    eng = EdgeEngine.from_policy(DEFAULT_POLICY)
    assert _eval(eng, 0.93, 0.89).suppression_reason == "prob_band"        # heavy favourite
    assert _eval(eng, 0.12, 0.08).suppression_reason == "prob_band"        # longshot
    # NO side: fair 0.10 vs market 0.14 -> bet NO at p=0.90 -> outside band
    assert _eval(eng, 0.10, 0.14).suppression_reason == "prob_band"


def test_default_engine_behaviour_unchanged():
    eng = EdgeEngine()  # legacy defaults: no min edge, no band
    assert _eval(eng, 0.52, 0.50).suppressed is False


def _sig(fair, price, win, i):
    return BacktestSignal(ticker=f"T{i}", kickoff=datetime(2026, 1, 1 + i % 28, tzinfo=timezone.utc),
                          model_fair=fair, market_price=price, edge=fair - price,
                          realized_outcome=win)


def test_kelly_config_from_policy_matches_bands_and_caps():
    cfg = KellyConfig.from_policy(DEFAULT_POLICY)
    assert cfg.fraction == 0.125 and cfg.max_stake_fraction == 0.02
    # in-band signal is bet; heavy-favourite and tiny-edge signals are not
    bet = [_sig(0.55, 0.50, 1, i) for i in range(5)]
    skipped = [_sig(0.93, 0.89, 1, i + 5) for i in range(5)] + [_sig(0.52, 0.50, 1, i + 10) for i in range(5)]
    assert simulate_kelly_pnl(bet, cfg).n_bets == 5
    assert simulate_kelly_pnl(skipped, cfg).n_bets == 0


def test_per_bet_cap_limits_exposure():
    cfg = KellyConfig.from_policy(DEFAULT_POLICY)
    res = simulate_kelly_pnl([_sig(0.60, 0.50, 0, 0)], cfg)   # losing bet
    assert res.total_staked <= cfg.starting_bankroll * cfg.max_stake_fraction + 1e-9
