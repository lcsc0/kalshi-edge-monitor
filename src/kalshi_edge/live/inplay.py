"""In-play fair prices: pre-match goal rates scaled by time left, conditioned on the score.

Assumptions (all unvalidated): goals arrive as independent Poisson processes at the
pre-match rates, 46% of them in the first half and 54% in the second, uniformly within
each half; no score-effect (trailing teams pushing) and no red-card adjustment (the
monitor refuses to trade games with a red card).
"""
import math

from kalshi_edge.model.poisson import score_matrix

H1_SHARE = 0.46
H2_SHARE = 1.0 - H1_SHARE


def remaining_share(period: int, minute: float, status_name: str = "") -> float:
    """Fraction of a full match's expected goals still to come."""
    if period <= 1:
        if status_name == "STATUS_HALFTIME":
            return H2_SHARE
        left = 45.0 - minute if minute < 45 else 0.5  # first-half stoppage: ~30s left, say
        return max(left, 0.0) / 45.0 * H1_SHARE + H2_SHARE
    left = 90.0 - max(minute, 45.0) if minute < 90 else 1.0  # 2nd-half stoppage: ~1 min left
    return max(left, 0.0) / 45.0 * H2_SHARE


def inplay_matrix(lam: float, mu: float, hs: int, as_: int, share: float,
                  max_goals: int = 10) -> list[list[float]]:
    """Joint distribution of *final* (home, away) goals, given current score and time left."""
    share = max(share, 1e-6)
    rem = score_matrix(lam * share, mu * share, rho=0.0, max_goals=max_goals)
    n = max_goals + 1
    final = [[0.0] * (as_ + n) for _ in range(hs + n)]
    for i, row in enumerate(rem):
        for j, p in enumerate(row):
            final[hs + i][as_ + j] = p
    return final


def kalshi_fee(price: float, contracts: float) -> float:
    """Taker fee in dollars: ceil_to_cent(0.07 * C * P * (1 - P)). Assumed from Kalshi's
    published schedule; check it against your account before trusting any P&L."""
    return math.ceil(round(0.07 * contracts * price * (1.0 - price) * 100, 6)) / 100.0
