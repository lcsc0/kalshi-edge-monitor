import random
from datetime import datetime, timedelta, timezone

import pytest

from kalshi_edge.backtest.replay import BacktestSignal
from kalshi_edge.backtest.edge_metrics import KellyConfig
from kalshi_edge.backtest.harness import BacktestReport, run_backtest, render_report

T0 = datetime(2025, 1, 1, tzinfo=timezone.utc)


def sig(model_fair, market_price, outcome, i=0):
    return BacktestSignal(
        ticker=f"T{i}", kickoff=T0 + timedelta(hours=i),
        model_fair=model_fair, market_price=market_price,
        edge=model_fair - market_price, realized_outcome=outcome)


def test_run_backtest_bundles_all_metrics():
    signals = [sig(0.60, 0.50, 1, i) for i in range(30)]
    rep = run_backtest(signals)
    assert isinstance(rep, BacktestReport)
    assert rep.n_signals == 30
    assert rep.n_flagged == 30
    assert len(rep.calibration) == 10
    assert rep.kelly.n_bets == 30
    assert rep.flat.n_bets == 30
    assert isinstance(rep.has_edge, bool)


def test_render_report_contains_verdict_and_roi():
    rep = run_backtest([sig(0.60, 0.50, 1, i) for i in range(20)])
    text = render_report(rep)
    assert "EDGE" in text.upper()
    assert "ROI" in text.upper()
    assert ("YES" in text.upper()) or ("NO" in text.upper())


# --------------------------------------------------------------------------- #
# Synthetic validation: the harness must catch a bad model.
# --------------------------------------------------------------------------- #

def _edged_signals(n, seed, edge=0.06):
    """Well-calibrated AND genuinely edged: model_fair == true win prob, the
    market underprices YES by a fixed `edge`, outcome ~ Bernoulli(true_p)."""
    rng = random.Random(seed)
    out = []
    for i in range(n):
        true_p = rng.uniform(0.15, 0.85)
        price = true_p - edge  # market underprices -> real, positive edge
        out.append(sig(true_p, price, 1 if rng.random() < true_p else 0, i))
    return out


def _no_edge_signals(n, seed):
    """No edge: model_fair is pure noise; the market is efficient, so outcomes
    follow the market price, not the model. Flagged edges are spurious."""
    rng = random.Random(seed)
    out = []
    for i in range(n):
        price = rng.uniform(0.15, 0.85)
        model_fair = rng.uniform(0.05, 0.95)  # uncorrelated with the outcome
        out.append(sig(model_fair, price, 1 if rng.random() < price else 0, i))
    return out


def test_harness_flags_a_genuinely_edged_model():
    rep = run_backtest(_edged_signals(4000, seed=7))
    assert rep.has_edge is True
    assert rep.positive_edge_lift > 0.0
    assert rep.kelly.roi > 0.0
    assert rep.kelly.final_bankroll > rep.kelly.starting_bankroll


def test_harness_rejects_a_no_edge_model():
    rep = run_backtest(_no_edge_signals(4000, seed=11))
    assert rep.has_edge is False
    assert abs(rep.positive_edge_lift) < 0.02   # flagged edge does not translate
    assert rep.kelly.roi < 0.02                 # no positive P&L from noise


def test_scripts_run_backtest_imports():
    import scripts.run_edge_backtest as rb
    assert hasattr(rb, "main")
