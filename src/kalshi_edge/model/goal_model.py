from kalshi_edge.model.poisson import score_matrix, outcome_probs
from kalshi_edge.model.strengths import team_strengths, DEFAULT_HALF_LIFE_DAYS


class GoalModel:
    """v1 ratio-based Poisson strength model with Dixon-Coles low-score correction.

    Not a full MLE fit (documented future improvement); validated by the backtest.
    """

    def __init__(self, mu: float, home_factor: float, teams: dict,
                 rho: float = 0.0, max_goals: int = 10):
        self.mu = mu
        self.home_factor = home_factor
        self.teams = teams
        self.rho = rho
        self.max_goals = max_goals

    @classmethod
    def from_db(cls, conn, ref_date: str, half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
                since: str | None = None, rho: float = 0.0, max_goals: int = 10) -> "GoalModel":
        s = team_strengths(conn, ref_date, half_life_days, since)
        return cls(s["mu"], s["home_factor"], s["teams"], rho=rho, max_goals=max_goals)

    def expected_goals(self, home: str, away: str, neutral: bool = True) -> tuple[float, float]:
        for t in (home, away):
            if t not in self.teams:
                raise ValueError(f"unknown team: {t!r}")
        th, ta = self.teams[home], self.teams[away]
        hf = 1.0 if neutral else self.home_factor
        lam = self.mu * th["attack"] * ta["defense"] * hf
        mu_ = self.mu * ta["attack"] * th["defense"] / hf
        return lam, mu_

    def joint_matrix(self, home: str, away: str, neutral: bool = True) -> list[list[float]]:
        lam, mu_ = self.expected_goals(home, away, neutral)
        return score_matrix(lam, mu_, self.rho, self.max_goals)

    def match_probabilities(self, home: str, away: str, neutral: bool = True) -> dict:
        return outcome_probs(self.joint_matrix(home, away, neutral))

    def analysis(self, home: str, away: str, neutral: bool = True) -> dict:
        lam, mu_ = self.expected_goals(home, away, neutral)
        return {
            "home": home, "away": away, "neutral": neutral,
            "expected_goals": {"home": lam, "away": mu_},
            "strength": {home: self.teams[home], away: self.teams[away]},
            "outcome_probs": self.match_probabilities(home, away, neutral),
        }
