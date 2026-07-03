"""Kalshi soccer contract types as predicates over a joint score matrix.

A contract's fair probability is the sum of joint-matrix cells (x=home goals,
y=away goals) where its predicate holds. Totals lines are half-integers (2.5,
3.5, ...) so no push is possible. Regulation time only (matches the model).
"""
from collections.abc import Callable

Predicate = Callable[[int, int], bool]


def price_predicate(matrix: list[list[float]], predicate: Predicate) -> float:
    """Sum matrix cells where `predicate(home_goals, away_goals)` is True."""
    return sum(
        p
        for x, row in enumerate(matrix)
        for y, p in enumerate(row)
        if predicate(x, y)
    )


# --- moneyline (regulation) ---
def home_win(x: int, y: int) -> bool:
    return x > y


def draw(x: int, y: int) -> bool:
    return x == y


def away_win(x: int, y: int) -> bool:
    return x < y


# --- double chance ---
def home_or_draw(x: int, y: int) -> bool:
    return x >= y


def away_or_draw(x: int, y: int) -> bool:
    return x <= y


def not_draw(x: int, y: int) -> bool:
    return x != y


# --- totals (match total goals) ---
def over(line: float) -> Predicate:
    """P(total goals > line); line is a half-integer, e.g. over(2.5) => total >= 3."""
    return lambda x, y: (x + y) > line


def under(line: float) -> Predicate:
    return lambda x, y: (x + y) < line


# --- both teams to score ---
def both_teams_score(x: int, y: int) -> bool:
    return x >= 1 and y >= 1


def both_teams_score_no(x: int, y: int) -> bool:
    return x == 0 or y == 0


# --- team totals ---
def _goals(side: str, x: int, y: int) -> int:
    if side == "home":
        return x
    if side == "away":
        return y
    raise ValueError(f"side must be 'home' or 'away', got {side!r}")


def team_over(side: str, line: float) -> Predicate:
    _goals(side, 0, 0)  # validate side eagerly
    return lambda x, y: _goals(side, x, y) > line


def team_under(side: str, line: float) -> Predicate:
    _goals(side, 0, 0)
    return lambda x, y: _goals(side, x, y) < line


# --- clean sheet (named side concedes zero) ---
def clean_sheet(side: str) -> Predicate:
    _goals(side, 0, 0)
    other = "away" if side == "home" else "home"
    return lambda x, y: _goals(other, x, y) == 0


# --- exact score ---
def exact_score(home_goals: int, away_goals: int) -> Predicate:
    return lambda x, y: x == home_goals and y == away_goals
