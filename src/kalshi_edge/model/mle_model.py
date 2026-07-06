import math
from kalshi_edge.model.poisson import score_matrix, outcome_probs
from kalshi_edge.model.mle import fit_dixon_coles, DCFit, DEFAULT_HALF_LIFE_DAYS


class MLEGoalModel:
    """Opponent-adjusted Dixon-Coles MLE model, drop-in for GoalModel."""

    def __init__(self, fit: DCFit, max_goals: int = 10):
        self.fit = fit
        self.max_goals = max_goals

    @classmethod
    def from_db(cls, conn, ref_date: str, since: str | None = None,
                half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
                min_games: int = 20, max_goals: int = 10) -> "MLEGoalModel":
        return cls(fit_dixon_coles(conn, ref_date, since, half_life_days, min_games),
                   max_goals=max_goals)

    def expected_goals(self, home: str, away: str, neutral: bool = True) -> tuple[float, float]:
        for t in (home, away):
            if t not in self.fit.attack:
                raise ValueError(f"unknown team: {t!r}")
        home_term = 0.0 if neutral else self.fit.home_adv
        lam = math.exp(self.fit.attack[home] - self.fit.defense[away] + home_term)
        mu = math.exp(self.fit.attack[away] - self.fit.defense[home])
        return lam, mu

    def joint_matrix(self, home: str, away: str, neutral: bool = True) -> list[list[float]]:
        lam, mu = self.expected_goals(home, away, neutral)
        return score_matrix(lam, mu, self.fit.rho, self.max_goals)

    def match_probabilities(self, home: str, away: str, neutral: bool = True) -> dict:
        return outcome_probs(self.joint_matrix(home, away, neutral))

    def analysis(self, home: str, away: str, neutral: bool = True) -> dict:
        lam, mu = self.expected_goals(home, away, neutral)
        return {
            "home": home, "away": away, "neutral": neutral,
            "expected_goals": {"home": lam, "away": mu},
            "strength": {
                home: {"attack": self.fit.attack[home], "defense": self.fit.defense[home]},
                away: {"attack": self.fit.attack[away], "defense": self.fit.defense[away]},
            },
            "outcome_probs": self.match_probabilities(home, away, neutral),
        }
