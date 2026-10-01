from datetime import datetime, timedelta, timezone

import pytest

from kalshi_edge.backtest.replay import BacktestSignal
from kalshi_edge.backtest.edge_metrics import (
    calibration_table,
    calibration_error,
    brier_score,
    hit_rate_by_edge_bucket,
    KellyConfig,
    simulate_kelly_pnl,
    simulate_flat_pnl,
)

T0 = datetime(2025, 1, 1, tzinfo=timezone.utc)


def sig(model_fair, market_price, outcome, i=0):
    return BacktestSignal(
        ticker=f"T{i}", kickoff=T0 + timedelta(hours=i),
        model_fair=model_fair, market_price=market_price,
        edge=model_fair - market_price, realized_outcome=outcome)


# ---- calibration ----

def test_calibration_perfectly_calibrated_has_low_error():
    # In each decile, realized rate matches the bin's predicted mean.
    signals = []
    i = 0
    for center in [0.05, 0.15, 0.25, 0.35, 0.45, 0.55, 0.65, 0.75, 0.85, 0.95]:
        wins = int(round(center * 100))
        for k in range(100):
            signals.append(sig(center, center, 1 if k < wins else 0, i)); i += 1
    err = calibration_error(signals, n_bins=10)
    assert err < 0.02
    table = calibration_table(signals, n_bins=10)
    assert len(table) == 10
    assert sum(b.count for b in table) == len(signals)


def test_brier_score_perfect_vs_worst():
    perfect = [sig(1.0, 0.5, 1), sig(0.0, 0.5, 0)]
    worst = [sig(0.0, 0.5, 1), sig(1.0, 0.5, 0)]
    assert brier_score(perfect) == pytest.approx(0.0)
    assert brier_score(worst) == pytest.approx(1.0)


# ---- edge buckets ----

def test_edge_buckets_partition_and_compute_lift():
    # A positive-edge signal that wins: realized rate 1.0 vs implied price 0.50 -> lift +0.50
    signals = [sig(0.70, 0.50, 1), sig(0.70, 0.50, 1)]
    buckets = hit_rate_by_edge_bucket(signals)
    hot = [b for b in buckets if b.count > 0]
    assert len(hot) == 1
    b = hot[0]
    assert b.lo >= 0.10  # 20pp edge lands in the top bucket
    assert b.realized_rate == pytest.approx(1.0)
    assert b.avg_market_price == pytest.approx(0.50)
    assert b.lift == pytest.approx(0.50)


# ---- Kelly P&L ----

def test_kelly_pnl_grows_bankroll_on_winning_positive_edge():
    signals = [sig(0.60, 0.50, 1, i) for i in range(20)]
    res = simulate_kelly_pnl(signals, KellyConfig(fraction=0.25, starting_bankroll=1000.0))
    assert res.n_bets == 20
    assert res.total_pnl > 0
    assert res.roi > 0
    assert res.final_bankroll > 1000.0
    assert res.max_drawdown >= 0.0


def test_kelly_pnl_loses_on_losing_positive_edge():
    signals = [sig(0.60, 0.50, 0, i) for i in range(20)]  # flagged but all lose
    res = simulate_kelly_pnl(signals, KellyConfig(starting_bankroll=1000.0))
    assert res.total_pnl < 0
    assert res.roi < 0


def test_kelly_suppresses_absurd_edges_and_skips_non_positive():
    # edge = 0.40 (> max_edge) is suppressed; edge <= 0 is not flagged.
    signals = [sig(0.95, 0.55, 1, 0), sig(0.40, 0.50, 1, 1)]
    res = simulate_kelly_pnl(signals, KellyConfig(max_edge=0.15, starting_bankroll=1000.0))
    assert res.n_bets == 0  # both excluded


def test_flat_baseline_runs_and_counts_flagged():
    signals = [sig(0.60, 0.50, 1, i) for i in range(10)]
    res = simulate_flat_pnl(signals, KellyConfig(starting_bankroll=1000.0))
    assert res.n_bets == 10
    assert res.total_pnl > 0
