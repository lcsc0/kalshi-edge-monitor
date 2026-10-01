"""Pure metrics over a list of :class:`BacktestSignal`.

Three families, all stdlib:

* **Calibration** — bin signals by ``model_fair`` and compare each bin's
  predicted mean to its realized hit-rate (plus a scalar error and Brier score).
* **Hit-rate by edge bucket** — the core "does flagged edge translate to wins"
  table: realized win-rate and count per edge band, with the *lift* of realized
  outcomes over the price you would have paid.
* **Simulated fractional-Kelly P&L** — walk the signals chronologically, stake
  fractional Kelly under the §3 hard caps, settle, track bankroll / ROI / drawdown.
  A flat-stake baseline is provided for comparison.

De-vig / edge math is deliberately self-contained here (the live ``edge_engine``
is a separate component).
"""
from dataclasses import dataclass, field

from kalshi_edge.backtest.replay import BacktestSignal


# --------------------------------------------------------------------------- #
# Calibration
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class CalibrationBin:
    lo: float
    hi: float
    count: int
    predicted_mean: float   # mean model_fair in the bin
    realized_rate: float    # fraction that settled in the money


def calibration_table(signals: list[BacktestSignal], n_bins: int = 10) -> list[CalibrationBin]:
    """Deciles (by default) of ``model_fair`` vs realized hit-rate."""
    edges = [i / n_bins for i in range(n_bins + 1)]
    out: list[CalibrationBin] = []
    for b in range(n_bins):
        lo, hi = edges[b], edges[b + 1]
        # last bin is closed on the right so model_fair == 1.0 lands somewhere
        in_bin = [s for s in signals
                  if s.model_fair >= lo and (s.model_fair < hi or (b == n_bins - 1 and s.model_fair <= hi))]
        n = len(in_bin)
        pred = sum(s.model_fair for s in in_bin) / n if n else 0.0
        real = sum(s.realized_outcome for s in in_bin) / n if n else 0.0
        out.append(CalibrationBin(lo=lo, hi=hi, count=n, predicted_mean=pred, realized_rate=real))
    return out


def calibration_error(signals: list[BacktestSignal], n_bins: int = 10) -> float:
    """Count-weighted mean absolute deviation between predicted and realized."""
    table = calibration_table(signals, n_bins)
    total = sum(b.count for b in table)
    if total == 0:
        return 0.0
    return sum(b.count * abs(b.predicted_mean - b.realized_rate) for b in table) / total


def brier_score(signals: list[BacktestSignal]) -> float:
    """Mean squared error of ``model_fair`` against the realized 0/1 outcome."""
    if not signals:
        return 0.0
    return sum((s.model_fair - s.realized_outcome) ** 2 for s in signals) / len(signals)


# --------------------------------------------------------------------------- #
# Hit-rate by edge bucket
# --------------------------------------------------------------------------- #

# (lo, hi, label) — edge in probability points; lo inclusive, hi exclusive.
DEFAULT_EDGE_BUCKETS = [
    (-1.0, 0.0, "<0"),
    (0.0, 0.02, "0-2pp"),
    (0.02, 0.05, "2-5pp"),
    (0.05, 0.10, "5-10pp"),
    (0.10, 1.01, "10pp+"),
]


@dataclass(frozen=True)
class EdgeBucket:
    label: str
    lo: float
    hi: float
    count: int
    realized_rate: float     # fraction that settled in the money
    avg_market_price: float  # mean price paid (implied rate)
    avg_model_fair: float
    lift: float              # realized_rate - avg_market_price (did it beat the price?)


def hit_rate_by_edge_bucket(signals: list[BacktestSignal],
                            buckets=DEFAULT_EDGE_BUCKETS) -> list[EdgeBucket]:
    out: list[EdgeBucket] = []
    for lo, hi, label in buckets:
        band = [s for s in signals if lo <= s.edge < hi]
        n = len(band)
        real = sum(s.realized_outcome for s in band) / n if n else 0.0
        price = sum(s.market_price for s in band) / n if n else 0.0
        fair = sum(s.model_fair for s in band) / n if n else 0.0
        out.append(EdgeBucket(label=label, lo=lo, hi=hi, count=n, realized_rate=real,
                              avg_market_price=price, avg_model_fair=fair, lift=real - price))
    return out


# --------------------------------------------------------------------------- #
# Fractional-Kelly P&L
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class KellyConfig:
    """Sizing policy for the P&L walk, mirroring §3 guardrails."""
    fraction: float = 0.25            # fractional Kelly (never full)
    max_edge: float = 0.15            # absurd-edge suppression: skip edges above this
    min_edge: float = 0.0             # only bet strictly positive edge (> min_edge)
    max_stake_fraction: float = 0.05  # per-bet exposure cap (fraction of bankroll)
    starting_bankroll: float = 1000.0
    min_side_prob: float = 0.0        # model_fair must lie in [min_side_prob, max_side_prob]
    max_side_prob: float = 1.0

    @classmethod
    def from_policy(cls, policy, starting_bankroll: float = 1000.0) -> "KellyConfig":
        """Sizing/selection identical to the live `EdgeEngine.from_policy` strategy."""
        return cls(fraction=policy.kelly_fraction, max_edge=policy.max_edge,
                   min_edge=policy.min_edge - 1e-12,  # policy bound is inclusive
                   max_stake_fraction=policy.max_stake_fraction,
                   starting_bankroll=starting_bankroll,
                   min_side_prob=policy.min_side_prob, max_side_prob=policy.max_side_prob)


@dataclass
class PnLResult:
    starting_bankroll: float
    final_bankroll: float
    total_pnl: float
    total_staked: float
    roi: float
    max_drawdown: float          # largest peak-to-trough drop, as a fraction of peak
    n_bets: int
    bankroll_curve: list[float] = field(default_factory=list)


def _is_flagged(s: BacktestSignal, cfg: KellyConfig) -> bool:
    return (cfg.min_edge < s.edge <= cfg.max_edge and 0.0 < s.market_price < 1.0
            and cfg.min_side_prob <= s.model_fair <= cfg.max_side_prob)


def _kelly_stake_fraction(edge: float, price: float, cfg: KellyConfig) -> float:
    """Fraction of bankroll to risk. Kelly for a YES contract at ``price`` with
    model win-prob ``price + edge`` is ``edge / (1 - price)``; scaled by
    ``fraction`` and capped by ``max_stake_fraction``."""
    kelly = edge / (1.0 - price)
    return min(cfg.fraction * kelly, cfg.max_stake_fraction)


def _settle(stake: float, price: float, outcome: int) -> float:
    """P&L of risking ``stake`` on YES at ``price``. Win pays net odds
    ``(1 - price) / price`` per unit risked; loss forfeits the stake."""
    if outcome:
        return stake * (1.0 - price) / price
    return -stake


def _walk(signals: list[BacktestSignal], cfg: KellyConfig, stake_fn) -> PnLResult:
    bankroll = cfg.starting_bankroll
    peak = bankroll
    max_dd = 0.0
    total_pnl = 0.0
    total_staked = 0.0
    n_bets = 0
    curve = [bankroll]
    for s in sorted(signals, key=lambda x: x.kickoff):
        if not _is_flagged(s, cfg):
            continue
        stake = stake_fn(s, bankroll)
        if stake <= 0:
            continue
        pnl = _settle(stake, s.market_price, s.realized_outcome)
        bankroll += pnl
        total_pnl += pnl
        total_staked += stake
        n_bets += 1
        curve.append(bankroll)
        peak = max(peak, bankroll)
        if peak > 0:
            max_dd = max(max_dd, (peak - bankroll) / peak)
    roi = total_pnl / total_staked if total_staked else 0.0
    return PnLResult(starting_bankroll=cfg.starting_bankroll, final_bankroll=bankroll,
                     total_pnl=total_pnl, total_staked=total_staked, roi=roi,
                     max_drawdown=max_dd, n_bets=n_bets, bankroll_curve=curve)


def simulate_kelly_pnl(signals: list[BacktestSignal], config: KellyConfig = KellyConfig()) -> PnLResult:
    """Chronological fractional-Kelly walk with §3 caps and absurd-edge suppression."""
    def stake_fn(s, bankroll):
        return bankroll * _kelly_stake_fraction(s.edge, s.market_price, config)
    return _walk(signals, config, stake_fn)


def simulate_flat_pnl(signals: list[BacktestSignal], config: KellyConfig = KellyConfig()) -> PnLResult:
    """Flat-stake baseline: a fixed fraction of the *starting* bankroll per flagged bet."""
    flat = config.starting_bankroll * config.max_stake_fraction

    def stake_fn(s, bankroll):
        return flat
    return _walk(signals, config, stake_fn)
