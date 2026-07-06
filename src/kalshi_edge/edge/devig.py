"""Remove the vig / overround from Kalshi contract prices.

Kalshi prices already *are* probabilities (dollars 0..1; each contract pays $1).
For a market whose N contracts partition the outcome space (e.g. home/draw/away
moneyline), the sum of the market's prices exceeds 1 by the overround. The
proportional ("basic") de-vig normalises the prices so they sum to 1, which
preserves their relative ordering.

A *lone* binary market (a single yes/no contract) has no partition to normalise:
a yes at ``p`` and its implied no at ``1 - p`` already sum to 1, so there is no
overround to remove beyond the bid/ask spread. For such a market the mid price
*is* the market's implied probability (``devig_single``); we do not add the
spread back in.
"""
from collections.abc import Mapping


def devig(prices: Mapping[str, float]) -> dict[str, float]:
    """Proportionally normalise a partition of Kalshi prices to sum to 1.

    Args:
        prices: contract-name -> Kalshi price (dollars 0..1) for a set of
            mutually-exclusive, collectively-exhaustive contracts.

    Returns:
        Fair probabilities (same keys) summing to 1.0.

    Raises:
        ValueError: if the prices are empty or sum to a non-positive value.
    """
    total = sum(prices.values())
    if total <= 0:
        raise ValueError(f"prices must sum to a positive value, got {total!r}")
    return {name: price / total for name, price in prices.items()}


def devig_single(yes_mid: float) -> float:
    """Implied probability of a lone binary market: its mid price.

    There is no partition to normalise, so the mid is returned unchanged. See the
    module docstring for why no vig is removed on a standalone yes/no market.
    """
    return yes_mid
