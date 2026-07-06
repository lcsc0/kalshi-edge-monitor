import math


def player_goal_share(conn, scorer: str, team: str, since: str | None = None) -> float:
    """Player's share of their team's total (non-own) goals over the window."""
    args_team = [team]
    args_player = [scorer, team]
    tail = ""
    if since:
        tail = " AND date >= ?"
        args_team.append(since)
        args_player.append(since)
    team_goals = conn.execute(
        "SELECT COUNT(*) FROM goals WHERE team = ? AND own_goal = 0" + tail, args_team
    ).fetchone()[0]
    if team_goals == 0:
        return 0.0
    player_goals = conn.execute(
        "SELECT COUNT(*) FROM goals WHERE scorer = ? AND team = ? AND own_goal = 0" + tail,
        args_player
    ).fetchone()[0]
    return player_goals / team_goals


def player_score_prob(goal_share: float, team_expected_goals: float) -> float:
    """P(player scores >= 1) = 1 - exp(-share * team_xg)."""
    lam = goal_share * team_expected_goals
    return 1 - math.exp(-lam)
