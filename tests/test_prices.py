from kalshi_edge.pricer.prices import moneyline, total_over, total_under, team_total_over, btts, correct_score

# matrix[home][away]; home in {0,1}, away in {0,1}
M = [[0.1, 0.2], [0.3, 0.4]]


def test_moneyline_splits_home_draw_away():
    p = moneyline(M)
    assert round(p["home"], 6) == 0.3   # (1,0)
    assert round(p["draw"], 6) == 0.5   # (0,0)+(1,1)
    assert round(p["away"], 6) == 0.2   # (0,1)
    assert round(p["home"] + p["draw"] + p["away"], 6) == 1.0


def test_total_over_and_under_are_complementary():
    assert round(total_over(M, 0.5), 6) == 0.9
    assert round(total_over(M, 1.5), 6) == 0.4
    assert round(total_under(M, 1.5), 6) == 0.6


def test_team_total_over():
    assert round(team_total_over(M, 0.5, "home"), 6) == 0.7
    assert round(team_total_over(M, 0.5, "away"), 6) == 0.6


def test_btts_both_teams_score():
    assert round(btts(M), 6) == 0.4


def test_correct_score_exact_and_out_of_range():
    assert round(correct_score(M, 1, 0), 6) == 0.3
    assert correct_score(M, 5, 5) == 0.0
