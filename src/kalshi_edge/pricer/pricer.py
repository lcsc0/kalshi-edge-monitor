"""Fair prices for Kalshi soccer contracts from a joint score matrix.

`Pricer` wraps one match's joint matrix (from a `GoalModel`). Named methods
price the common contract types; `price(name, line=...)` dispatches by string.
Same-game combos are summed over the shared matrix (correlation priced exactly);
cross-game combos multiply the per-game leg probabilities (independence).
"""
from collections.abc import Sequence

from kalshi_edge.model.goal_model import GoalModel
from kalshi_edge.pricer import contracts

# Legs are (name,) or (name, line): "home"/"draw"/"away", "home_or_draw",
# "away_or_draw", "not_draw", "over"/"under" (needs line), "btts"/"btts_no",
# "home_over"/"home_under"/"away_over"/"away_under" (needs line),
# "home_spread"/"away_spread" (needs line), "home_clean_sheet"/"away_clean_sheet",
# "exact" (needs (h, a) as line).
Leg = tuple


def _predicate_for(name: str, line=None):
    simple = {
        "home": contracts.home_win,
        "draw": contracts.draw,
        "away": contracts.away_win,
        "home_or_draw": contracts.home_or_draw,
        "away_or_draw": contracts.away_or_draw,
        "not_draw": contracts.not_draw,
        "btts": contracts.both_teams_score,
        "btts_no": contracts.both_teams_score_no,
        "home_clean_sheet": contracts.clean_sheet("home"),
        "away_clean_sheet": contracts.clean_sheet("away"),
    }
    if name in simple:
        return simple[name]
    if name == "over":
        return contracts.over(line)
    if name == "under":
        return contracts.under(line)
    if name == "home_over":
        return contracts.team_over("home", line)
    if name == "home_under":
        return contracts.team_under("home", line)
    if name == "away_over":
        return contracts.team_over("away", line)
    if name == "away_under":
        return contracts.team_under("away", line)
    if name == "home_spread":
        return contracts.home_spread(line)
    if name == "away_spread":
        return contracts.away_spread(line)
    if name == "exact":
        return contracts.exact_score(line[0], line[1])
    raise ValueError(f"unknown contract: {name!r}")


class Pricer:
    def __init__(self, matrix: list[list[float]], home: str = "", away: str = ""):
        self.matrix = matrix
        self.home = home
        self.away = away

    @classmethod
    def from_model(cls, model: GoalModel, home: str, away: str,
                   neutral: bool = True) -> "Pricer":
        return cls(model.joint_matrix(home, away, neutral), home, away)

    # --- single contracts ---
    def price(self, name: str, line=None) -> float:
        return contracts.price_predicate(self.matrix, _predicate_for(name, line))

    def moneyline(self) -> dict:
        return {
            "home": self.price("home"),
            "draw": self.price("draw"),
            "away": self.price("away"),
        }

    def total_over(self, line: float) -> float:
        return self.price("over", line)

    def total_under(self, line: float) -> float:
        return self.price("under", line)

    def both_teams_score(self) -> float:
        return self.price("btts")

    # --- combos ---
    def _combo_predicate(self, legs: Sequence[Leg]):
        preds = [_predicate_for(leg[0], leg[1] if len(leg) > 1 else None) for leg in legs]
        return lambda x, y: all(p(x, y) for p in preds)

    def same_game_combo(self, legs: Sequence[Leg]) -> float:
        """P(all legs hit) within one match — summed over the shared matrix."""
        return contracts.price_predicate(self.matrix, self._combo_predicate(legs))

    @staticmethod
    def combo_across_games(games: Sequence[tuple["Pricer", Sequence[Leg]]]) -> float:
        """P(all legs hit) across independent matches — product of per-game combos."""
        prob = 1.0
        for pricer, legs in games:
            prob *= pricer.same_game_combo(legs)
        return prob
