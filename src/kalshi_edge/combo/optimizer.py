"""Combo optimizer (design §4.6).

Search today's eligible legs to **maximise the payout multiplier subject to a
joint hit-probability target** (the "smallest risk" knob). Correlation is priced
correctly: legs in the *same* game are combined over the shared joint matrix via
``Pricer.same_game_combo`` (never by multiplying marginals); independent games
multiply. Every leg must carry a positive model edge. A totals leg sitting on a
high-variance boundary is shifted to the safer bucket first (``safety_shift``).

The search is bounded by ``max_legs`` (default 4) so it stays tractable.
"""
from dataclasses import dataclass
from itertools import combinations
from typing import Optional

from kalshi_edge.pricer.pricer import Pricer


@dataclass
class ComboLeg:
    game_id: str            # groups legs from the same match (shared matrix)
    pricer: Pricer          # the match's pricer (joint score matrix)
    leg: tuple              # (name,) or (name, line), per the Pricer contract set
    model_fair: float       # model probability this leg hits
    market_price: float     # cost to buy (dollars 0..1); drives the multiplier
    edge: float             # model_fair - market_implied; must be > 0 to be used


@dataclass
class Combo:
    legs: list[ComboLeg]
    joint_prob: float       # model probability all legs hit (correlation-aware)
    multiplier: float       # payout multiplier = product of decimal odds


def joint_prob(legs: list[ComboLeg]) -> float:
    """Model probability that every leg hits.

    Legs are grouped by ``game_id``; each game's legs are priced together over its
    shared joint matrix (``same_game_combo``), and the per-game probabilities are
    multiplied across independent games.
    """
    by_game: dict[str, list[ComboLeg]] = {}
    for leg in legs:
        by_game.setdefault(leg.game_id, []).append(leg)
    prob = 1.0
    for game_legs in by_game.values():
        pricer = game_legs[0].pricer
        prob *= pricer.same_game_combo([lg.leg for lg in game_legs])
    return prob


def multiplier(legs: list[ComboLeg]) -> float:
    """Payout multiplier = product of each leg's decimal odds (1 / market_price)."""
    mult = 1.0
    for leg in legs:
        mult *= 1.0 / leg.market_price
    return mult


def optimize(legs: list[ComboLeg], target_prob: float,
             max_legs: int = 4) -> Optional[Combo]:
    """Best combo: maximise multiplier subject to ``joint_prob >= target_prob``.

    Only legs with a positive model edge are considered. Combos of size 1..``max_legs``
    are searched. Returns the feasible combo with the largest multiplier, or ``None``
    if no combination of eligible legs meets the target.
    """
    eligible = [leg for leg in legs if leg.edge > 0]
    best: Optional[Combo] = None
    upper = min(max_legs, len(eligible))
    for size in range(1, upper + 1):
        for subset in combinations(eligible, size):
            subset = list(subset)
            jp = joint_prob(subset)
            if jp < target_prob:
                continue
            mult = multiplier(subset)
            if best is None or mult > best.multiplier:
                best = Combo(legs=subset, joint_prob=jp, multiplier=mult)
    return best


def _expected_total(pricer: Pricer) -> float:
    return sum((x + y) * p
               for x, row in enumerate(pricer.matrix)
               for y, p in enumerate(row))


def safety_shift(leg: tuple, pricer: Pricer, window: float = 1.0,
                 step: float = 1.0) -> tuple:
    """Shift a boundary totals leg to the safer bucket (design §4.6).

    When a totals leg's line sits within ``window`` of the match's expected total
    goals — a high-variance boundary — prefer the safer bucket: ``under`` moves up
    (under-2.5 -> under-3.5), ``over`` moves down. Non-totals legs and lines far
    from the expectation are returned unchanged.
    """
    if not leg or leg[0] not in ("over", "under"):
        return leg
    name, line = leg[0], leg[1]
    if abs(_expected_total(pricer) - line) > window:
        return leg
    return (name, line + step) if name == "under" else (name, line - step)
