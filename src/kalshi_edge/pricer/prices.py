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
