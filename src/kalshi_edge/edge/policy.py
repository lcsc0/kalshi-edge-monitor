"""Single source of truth for the "small wins, long term" betting policy.

Both the live `EdgeEngine` and the backtest's `KellyConfig` are built from this
one object so the strategy that is validated is the strategy that is traded.

Defaults are deliberately conservative and chosen from the real-data backtest of
the MLE goal model (2023-24, 2,167 matches): the model is well calibrated overall
but mildly overconfident above ~80%, so the probability band keeps singles away
from the extremes where an apparent edge is most likely model error.

* Singles only (no combos) — combos compound model error across legs.
* Edge band ``[min_edge, max_edge]`` — ignore noise-level edges; treat large
  edges as probable errors rather than opportunities.
* Side-probability band — the probability the *chosen side* wins must sit in
  ``[min_side_prob, max_side_prob]``.
* Eighth-Kelly with a small per-bet bankroll cap so no single result matters.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class StrategyPolicy:
    min_edge: float = 0.03          # need >= 3pp edge over the de-vigged market
    max_edge: float = 0.10          # >10pp is a probable model/data error
    min_side_prob: float = 0.15     # skip longshots (worst-calibrated tail)
    max_side_prob: float = 0.85     # skip heavy favourites (model overconfident >80%)
    kelly_fraction: float = 0.125   # 1/8 Kelly
    max_stake_fraction: float = 0.02  # <=2% of bankroll on any single bet
    max_slippage: float = 0.02
    intended_size: int = 100
    allow_combos: bool = False

    def __post_init__(self):
        if not 0.0 <= self.min_edge < self.max_edge <= 1.0:
            raise ValueError("require 0 <= min_edge < max_edge <= 1")
        if not 0.0 <= self.min_side_prob < self.max_side_prob <= 1.0:
            raise ValueError("require 0 <= min_side_prob < max_side_prob <= 1")
        if not 0.0 < self.kelly_fraction < 1.0:
            raise ValueError("kelly_fraction must be in (0, 1) — never full Kelly")


DEFAULT_POLICY = StrategyPolicy()


def side_prob(model_fair: float, side: str) -> float:
    """Probability that the chosen side (``"yes"``/``"no"``) wins."""
    return model_fair if side == "yes" else 1.0 - model_fair
