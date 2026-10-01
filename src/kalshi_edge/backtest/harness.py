"""Tie the backtest metrics together into a single report + a text renderer.

``run_backtest`` bundles calibration, edge-bucket hit-rates and the fractional-
Kelly P&L (vs a flat baseline) and distills them into one ``has_edge`` verdict —
the gate that clears the design's "UNVALIDATED MODEL" banner (§9). The verdict is
deliberately strict: the model only "has edge" when its flagged (positive-edge)
markets settled **above** the price you would have paid *and* the simulated
fractional-Kelly walk was profitable.
"""
from dataclasses import dataclass, field

from kalshi_edge.backtest.replay import BacktestSignal
from kalshi_edge.backtest.edge_metrics import (
    CalibrationBin, EdgeBucket, KellyConfig, PnLResult,
    DEFAULT_EDGE_BUCKETS,
    calibration_table, calibration_error, brier_score,
    hit_rate_by_edge_bucket, simulate_kelly_pnl, simulate_flat_pnl,
)

# Minimum count-weighted lift over positive-edge buckets to count as real signal.
LIFT_THRESHOLD = 0.01


@dataclass
class BacktestReport:
    n_signals: int
    n_flagged: int
    calibration: list[CalibrationBin]
    calibration_error: float
    brier: float
    edge_buckets: list[EdgeBucket]
    kelly: PnLResult
    flat: PnLResult
    positive_edge_lift: float   # count-weighted lift over edge>0 buckets
    has_edge: bool
    config: KellyConfig = field(default_factory=KellyConfig)


def _positive_edge_lift(buckets: list[EdgeBucket]) -> float:
    pos = [b for b in buckets if b.lo >= 0.0 and b.count > 0]
    total = sum(b.count for b in pos)
    if total == 0:
        return 0.0
    return sum(b.count * b.lift for b in pos) / total


def _n_flagged(signals: list[BacktestSignal], cfg: KellyConfig) -> int:
    return sum(1 for s in signals
               if cfg.min_edge < s.edge <= cfg.max_edge and 0.0 < s.market_price < 1.0)


def run_backtest(signals: list[BacktestSignal], config: KellyConfig = KellyConfig(),
                 n_bins: int = 10, edge_buckets=DEFAULT_EDGE_BUCKETS) -> BacktestReport:
    buckets = hit_rate_by_edge_bucket(signals, edge_buckets)
    lift = _positive_edge_lift(buckets)
    kelly = simulate_kelly_pnl(signals, config)
    flat = simulate_flat_pnl(signals, config)
    has_edge = (lift > LIFT_THRESHOLD) and (kelly.roi > 0.0)
    return BacktestReport(
        n_signals=len(signals),
        n_flagged=_n_flagged(signals, config),
        calibration=calibration_table(signals, n_bins),
        calibration_error=calibration_error(signals, n_bins),
        brier=brier_score(signals),
        edge_buckets=buckets,
        kelly=kelly,
        flat=flat,
        positive_edge_lift=lift,
        has_edge=has_edge,
        config=config,
    )


def _pct(x: float) -> str:
    return f"{x * 100:+.1f}%"


def render_report(report: BacktestReport) -> str:
    r = report
    verdict = "YES" if r.has_edge else "NO"
    lines = [
        "=" * 60,
        "KALSHI EDGE MONITOR — BACKTEST REPORT",
        "=" * 60,
        f"Signals: {r.n_signals}   Flagged (bet): {r.n_flagged}",
        f"Calibration error: {r.calibration_error:.4f}   Brier: {r.brier:.4f}",
        "",
        "Calibration (model_fair -> realized):",
    ]
    for b in r.calibration:
        if b.count:
            lines.append(f"  [{b.lo:.1f}-{b.hi:.1f})  n={b.count:<5d} "
                         f"pred={b.predicted_mean:.3f}  real={b.realized_rate:.3f}")

    lines += ["", "Hit-rate by edge bucket (realized vs price paid):"]
    for b in r.edge_buckets:
        if b.count:
            lines.append(f"  {b.label:<7s} n={b.count:<5d} "
                         f"realized={b.realized_rate:.3f} price={b.avg_market_price:.3f} "
                         f"lift={_pct(b.lift)}")

    lines += [
        "",
        f"Positive-edge lift (flagged settled above implied rate): {_pct(r.positive_edge_lift)}",
        "",
        "Simulated P&L (fractional Kelly vs flat baseline):",
        f"  Kelly: bets={r.kelly.n_bets}  ROI={_pct(r.kelly.roi)}  "
        f"P&L={r.kelly.total_pnl:+.2f}  bankroll {r.kelly.starting_bankroll:.0f}->"
        f"{r.kelly.final_bankroll:.2f}  maxDD={r.kelly.max_drawdown:.1%}",
        f"  Flat:  bets={r.flat.n_bets}  ROI={_pct(r.flat.roi)}  P&L={r.flat.total_pnl:+.2f}",
        "",
        "-" * 60,
        f"MODEL SHOWS EDGE: {verdict}"
        + ("" if r.has_edge else "   (UNVALIDATED banner stays up)"),
        "-" * 60,
    ]
    return "\n".join(lines)
