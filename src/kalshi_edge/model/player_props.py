"""Player-goals prop pricing (design §4 pricer: player-scores).

A player's expected goals in a match is the team's expected goals scaled by the
player's historical **share** of team goals::

    lam_player = team_lambda * (player goals / team goals)

and the "N+ goals" contract is priced as ``P(X >= N)`` for ``X ~ Poisson(lam_player)``.
Share comes from the SP2a ``goals`` table. This is a v1 attribution (no minutes /
lineup weighting yet — that is SP2d enrichment); the backtest validates it.
"""
import math

from kalshi_edge.data.intl_results import player_goal_count


def poisson_at_least(lam: float, k: int) -> float:
    """P(X >= k) for X ~ Poisson(lam). ``k <= 0`` is certain."""
    if k <= 0:
        return 1.0
    cdf = sum(math.exp(-lam) * lam ** i / math.factorial(i) for i in range(k))
    return max(0.0, 1.0 - cdf)


def team_goals_total(conn, team: str, since: str | None = None) -> int:
    """Total (non-own) goals scored by ``team`` in the goals table."""
    q = "SELECT COUNT(*) FROM goals WHERE team = ? AND own_goal = 0"
    args = [team]
    if since:
        q += " AND date >= ?"
        args.append(since)
    return conn.execute(q, args).fetchone()[0]


def player_share(conn, scorer: str, team: str, since: str | None = None) -> float:
    """Fraction of ``team``'s goals scored by ``scorer`` (0..1)."""
    total = team_goals_total(conn, team, since)
    if total <= 0:
        return 0.0
    return min(1.0, player_goal_count(conn, scorer, since) / total)


def player_expected_goals(team_lambda: float, share: float) -> float:
    return team_lambda * share


def player_goal_prob(conn, scorer: str, team: str, team_lambda: float,
                     threshold: int, since: str | None = None) -> float:
    """Fair probability that ``scorer`` scores at least ``threshold`` goals."""
    lam_p = player_expected_goals(team_lambda, player_share(conn, scorer, team, since))
    return poisson_at_least(lam_p, threshold)


def player_team(conn, scorer: str, candidates, since: str | None = None) -> str | None:
    """Whichever candidate team ``scorer`` has scored most for (or ``None``)."""
    best, best_n = None, 0
    for team in candidates:
        q = "SELECT COUNT(*) FROM goals WHERE scorer = ? AND team = ? AND own_goal = 0"
        args = [scorer, team]
        if since:
            q += " AND date >= ?"
            args.append(since)
        n = conn.execute(q, args).fetchone()[0]
        if n > best_n:
            best, best_n = team, n
    return best
