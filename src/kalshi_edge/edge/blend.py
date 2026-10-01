"""Adaptive model/market blend, learned per series from settled signals.

    fair = w * model + (1 - w) * market          (so  edge = w * (model - market))

``w`` minimises Brier loss; in closed form, with d = model - market,

    w* = sum(d * (y - market)) / sum(d * d)

The weight actually *used* is a one-sided **lower confidence bound** of w* (z=2.5,
~99.4%, because ~20 series are tested at once and a plain 95% bound lets ~1 through
by chance; on the club backtest that was exactly EPL totals),
clipped to [0, 1], and only with at least ``min_n`` settled signals. So a series
gets a non-zero weight only once the model has demonstrably added information
beyond the market price; until then w = 0, the blended fair equals the market, the
edge is exactly zero, and nothing is bet. Only this one number per series adapts;
team ratings and the model itself are never auto-tuned (too easy to overfit).
"""
import math
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable

Z_LOWER = 2.5  # one-sided ~99.4%: guards against picking a lucky series out of many


@dataclass(frozen=True)
class BlendFit:
    n: int
    w_hat: float        # unconstrained Brier-optimal weight
    se: float           # its standard error
    weight: float       # weight used: clip(w_hat - z*se, 0, 1), or 0 below min_n


def fit_blend(samples: Iterable[tuple[float, float, int]], min_n: int = 300,
              z: float = Z_LOWER) -> BlendFit:
    """``samples`` = (model_prob, market_prob, outcome 0/1)."""
    d, e = [], []
    for model, market, y in samples:
        d.append(model - market)
        e.append(y - market)
    n = len(d)
    sdd = sum(x * x for x in d)
    if n < 2 or sdd <= 1e-12:
        return BlendFit(n, 0.0, float("inf"), 0.0)
    w_hat = sum(x * y for x, y in zip(d, e)) / sdd
    resid = [y - w_hat * x for x, y in zip(d, e)]
    sigma2 = sum(r * r for r in resid) / (n - 1)
    se = math.sqrt(sigma2 / sdd)
    weight = 0.0 if n < min_n else max(0.0, min(1.0, w_hat - z * se))
    return BlendFit(n, w_hat, se, weight)


class BlendTable:
    """Per-series weights; callable as ``blend(series, model, market) -> fair``."""

    def __init__(self, fits: dict[str, BlendFit] | None = None):
        self.fits = fits or {}

    @classmethod
    def from_samples(cls, by_series: dict[str, list[tuple[float, float, int]]],
                     min_n: int = 300) -> "BlendTable":
        return cls({s: fit_blend(v, min_n) for s, v in by_series.items()})

    @classmethod
    def from_db(cls, conn, min_n: int = 300) -> "BlendTable":
        from kalshi_edge.edge.settle import settled_rows
        groups = defaultdict(list)
        for r in settled_rows(conn):
            groups[r["series"]].append((r["model"], r["market"], r["y"]))
        return cls.from_samples(groups, min_n)

    def weight(self, series: str) -> float:
        fit = self.fits.get(series)
        return fit.weight if fit else 0.0

    def __call__(self, series: str, model: float, market: float) -> float:
        w = self.weight(series)
        return w * model + (1.0 - w) * market

    def summary(self) -> str:
        lines = [f"{'series':24} {'n':>6} {'w_hat':>7} {'se':>7} {'weight used':>12}"]
        for s, f in sorted(self.fits.items()):
            lines.append(f"{s:24} {f.n:6d} {f.w_hat:7.3f} {f.se:7.3f} {f.weight:12.3f}")
        return "\n".join(lines)
