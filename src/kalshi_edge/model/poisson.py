import math


def dc_tau(x: int, y: int, lam: float, mu: float, rho: float) -> float:
    """Dixon-Coles low-score dependency adjustment (1.0 outside the four cells)."""
    if x == 0 and y == 0:
        return 1 - lam * mu * rho
    if x == 0 and y == 1:
        return 1 + lam * rho
    if x == 1 and y == 0:
        return 1 + mu * rho
    if x == 1 and y == 1:
        return 1 - rho
    return 1.0


def _poisson(k: int, mean: float) -> float:
    return math.exp(-mean) * mean ** k / math.factorial(k)


def score_matrix(lam: float, mu: float, rho: float = 0.0, max_goals: int = 10) -> list[list[float]]:
    """Joint P(home=x, away=y) as a (max_goals+1) x (max_goals+1) matrix, renormalized."""
    M = [[_poisson(x, lam) * _poisson(y, mu) * dc_tau(x, y, lam, mu, rho)
          for y in range(max_goals + 1)] for x in range(max_goals + 1)]
    total = sum(sum(row) for row in M)
    return [[v / total for v in row] for row in M]


def outcome_probs(matrix: list[list[float]]) -> dict:
    """Collapse a joint score matrix into home-win / draw / away-win probabilities."""
    home = draw = away = 0.0
    for x, row in enumerate(matrix):
        for y, p in enumerate(row):
            if x > y:
                home += p
            elif x == y:
                draw += p
            else:
                away += p
    return {"home": home, "draw": draw, "away": away}
