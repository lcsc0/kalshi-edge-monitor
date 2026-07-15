import math
from kalshi_edge.data.cache import connect
from kalshi_edge.data.intl_results import load_goalscorers_csv
from kalshi_edge.model.player_props import (
    poisson_at_least, team_goals_total, player_share, player_expected_goals,
    player_goal_prob, player_team,
)

# Argentina scores 10 goals: Messi 6, Alvarez 4. Brazil scores 5: Neymar 5.
GOALS = "date,home_team,away_team,team,scorer,minute,own_goal,penalty\n" + "".join(
    f"2025-01-0{d},Argentina,Brazil,Argentina,Lionel Messi,10,0,0\n" for d in range(1, 7)
) + "".join(
    f"2025-02-0{d},Argentina,Brazil,Argentina,Julian Alvarez,20,0,0\n" for d in range(1, 5)
) + "".join(
    f"2025-03-0{d},Argentina,Brazil,Brazil,Neymar,30,0,0\n" for d in range(1, 6)
)


def _conn():
    c = connect(); load_goalscorers_csv(c, GOALS); return c


def test_poisson_at_least_edges_and_value():
    assert poisson_at_least(1.3, 0) == 1.0          # "0+" always hits
    assert abs(poisson_at_least(1.0, 1) - (1 - math.exp(-1.0))) < 1e-9
    # P(>=2) < P(>=1)
    assert poisson_at_least(1.0, 2) < poisson_at_least(1.0, 1)


def test_team_total_and_share():
    c = _conn()
    assert team_goals_total(c, "Argentina") == 10
    assert abs(player_share(c, "Lionel Messi", "Argentina") - 0.6) < 1e-9
    assert abs(player_share(c, "Julian Alvarez", "Argentina") - 0.4) < 1e-9


def test_player_expected_goals_and_prob():
    c = _conn()
    # team lambda 2.0, Messi share 0.6 -> lam_p 1.2
    lam_p = player_expected_goals(2.0, player_share(c, "Lionel Messi", "Argentina"))
    assert abs(lam_p - 1.2) < 1e-9
    p = player_goal_prob(c, "Lionel Messi", "Argentina", team_lambda=2.0, threshold=1)
    assert abs(p - (1 - math.exp(-1.2))) < 1e-9
    # higher-share player is likelier to score
    assert (player_goal_prob(c, "Lionel Messi", "Argentina", 2.0, 1)
            > player_goal_prob(c, "Julian Alvarez", "Argentina", 2.0, 1))


def test_player_team_resolves_from_goals():
    c = _conn()
    assert player_team(c, "Lionel Messi", ["Argentina", "Brazil"]) == "Argentina"
    assert player_team(c, "Neymar", ["Argentina", "Brazil"]) == "Brazil"
    assert player_team(c, "Nobody", ["Argentina", "Brazil"]) is None
