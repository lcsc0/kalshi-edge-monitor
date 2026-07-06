"""Fractional-Kelly staking with the design §3 hard caps.

A Kalshi contract is a binary bet: you pay ``price`` (dollars 0..1) per contract
and it pays $1 if it settles YES. Full Kelly for that bet is

    f* = (p - price) / (1 - price)

(the fraction of bankroll to stake). Per §3 we **never** stake full Kelly — a
fraction (default 1/4) is applied — and the resulting dollar stake is floored by
the per-combo, per-game, and per-day exposure ceilings. Negative-edge bets clamp
to zero.
"""


def kelly_fraction(p: float, price: float) -> float:
    """Full-Kelly bankroll fraction for a YES contract at cost ``price``.

    Clamped to 0 when the bet has no edge (``p <= price``) or the price is
    degenerate (``price >= 1``).
    """
    if price >= 1.0 or price <= 0.0:
        return 0.0
    f = (p - price) / (1.0 - price)
    return f if f > 0.0 else 0.0


def fractional_kelly(p: float, price: float, fraction: float = 0.25) -> float:
    """A fraction (default 1/4) of full Kelly. Never full; clamped >= 0."""
    return fraction * kelly_fraction(p, price)


def size_bet(
    p: float,
    price: float,
    bankroll: float,
    *,
    fraction: float = 0.25,
    per_combo_cap: float | None = None,
    per_game_cap: float | None = None,
    per_day_cap: float | None = None,
    game_exposure: float = 0.0,
    day_exposure: float = 0.0,
) -> float:
    """Dollar stake = fractional Kelly of bankroll, floored by the tightest cap.

    Args:
        p: model probability the contract settles YES.
        price: cost per contract (dollars 0..1).
        bankroll: total staking bankroll in dollars.
        fraction: Kelly fraction (default 0.25).
        per_combo_cap: max dollars on this single bet/combo.
        per_game_cap: max total dollars exposed on this game.
        per_day_cap: max total dollars exposed today.
        game_exposure: dollars already staked on this game.
        day_exposure: dollars already staked today.

    Returns:
        The stake in dollars, >= 0.
    """
    stake = fractional_kelly(p, price, fraction) * bankroll
    limits = [stake]
    if per_combo_cap is not None:
        limits.append(per_combo_cap)
    if per_game_cap is not None:
        limits.append(per_game_cap - game_exposure)
    if per_day_cap is not None:
        limits.append(per_day_cap - day_exposure)
    return max(0.0, min(limits))
