import math
from kalshi_edge.data.cache import connect
from kalshi_edge.data.intl_results import load_goalscorers_csv
from kalshi_edge.pricer.players import player_goal_share, player_score_prob

GOALS = (
    "date,home_team,away_team,team,scorer,minute,own_goal,penalty\n"
    "2025-06-01,Portugal,Spain,Portugal,Ronaldo,10,FALSE,FALSE\n"
    "2025-06-01,Portugal,Spain,Portugal,Ronaldo,20,FALSE,FALSE\n"
    "2025-06-01,Portugal,Spain,Portugal,Silva,30,FALSE,FALSE\n"
    "2025-06-05,Portugal,France,Portugal,Ronaldo,40,FALSE,FALSE\n"
)


def test_player_goal_share_fraction_of_team_goals():
    conn = connect(); load_goalscorers_csv(conn, GOALS)
    assert round(player_goal_share(conn, "Ronaldo", "Portugal"), 4) == 0.75
    assert round(player_goal_share(conn, "Silva", "Portugal"), 4) == 0.25


def test_player_goal_share_zero_when_team_has_no_goals():
    conn = connect(); load_goalscorers_csv(conn, GOALS)
    assert player_goal_share(conn, "Ronaldo", "Nowhere") == 0.0


def test_player_score_prob_from_share_and_team_xg():
    assert round(player_score_prob(0.3, 1.5), 6) == round(1 - math.exp(-0.45), 6)
    assert player_score_prob(0.0, 1.5) == 0.0
