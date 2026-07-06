def _cells(matrix):
    for x, row in enumerate(matrix):
        for y, p in enumerate(row):
            yield x, y, p


def moneyline(matrix) -> dict:
    home = draw = away = 0.0
    for x, y, p in _cells(matrix):
        if x > y:
            home += p
        elif x == y:
            draw += p
        else:
            away += p
    return {"home": home, "draw": draw, "away": away}


def total_over(matrix, line: float) -> float:
    return sum(p for x, y, p in _cells(matrix) if x + y > line)


def total_under(matrix, line: float) -> float:
    return sum(p for x, y, p in _cells(matrix) if x + y < line)


def team_total_over(matrix, line: float, side: str) -> float:
    if side == "home":
        return sum(p for x, y, p in _cells(matrix) if x > line)
    if side == "away":
        return sum(p for x, y, p in _cells(matrix) if y > line)
    raise ValueError(f"side must be 'home' or 'away', got {side!r}")


def btts(matrix) -> float:
    return sum(p for x, y, p in _cells(matrix) if x >= 1 and y >= 1)


def correct_score(matrix, home_goals: int, away_goals: int) -> float:
    if 0 <= home_goals < len(matrix) and 0 <= away_goals < len(matrix[0]):
        return matrix[home_goals][away_goals]
    return 0.0
