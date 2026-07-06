import math
from collections import Counter

OUTCOMES = ("home", "draw", "away")


def brier_score(records: list[dict]) -> float:
    if not records:
        return 0.0
    total = 0.0
    for r in records:
        p, y = r["probs"], r["outcome"]
        total += sum((p[k] - (1.0 if k == y else 0.0)) ** 2 for k in OUTCOMES)
    return total / len(records)


def log_loss(records: list[dict], eps: float = 1e-15) -> float:
    if not records:
        return 0.0
    total = 0.0
    for r in records:
        p = min(max(r["probs"][r["outcome"]], eps), 1 - eps)
        total += -math.log(p)
    return total / len(records)


def accuracy(records: list[dict]) -> float:
    if not records:
        return 0.0
    hits = sum(1 for r in records if max(r["probs"], key=r["probs"].get) == r["outcome"])
    return hits / len(records)


def baseline_brier(records: list[dict]) -> float:
    """Climatology baseline: predict the overall outcome frequencies for every match."""
    if not records:
        return 0.0
    counts = Counter(r["outcome"] for r in records)
    n = len(records)
    base = {k: counts.get(k, 0) / n for k in OUTCOMES}
    total = 0.0
    for r in records:
        y = r["outcome"]
        total += sum((base[k] - (1.0 if k == y else 0.0)) ** 2 for k in OUTCOMES)
    return total / len(records)


def calibration_table(records: list[dict], outcome: str = "home", bins: int = 10) -> list[dict]:
    """Reliability table for a single outcome's predicted probability."""
    table = []
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        if b == bins - 1:
            sel = [r for r in records if lo <= r["probs"][outcome] <= hi]
        else:
            sel = [r for r in records if lo <= r["probs"][outcome] < hi]
        if not sel:
            continue
        avg_pred = sum(r["probs"][outcome] for r in sel) / len(sel)
        observed = sum(1 for r in sel if r["outcome"] == outcome) / len(sel)
        table.append({"bin": (lo, hi), "n": len(sel), "avg_pred": avg_pred, "observed": observed})
    return table
