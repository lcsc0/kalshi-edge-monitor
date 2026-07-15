import pytest
from kalshi_edge.model.poisson import score_matrix
from kalshi_edge.pricer.contracts import (
    price_predicate, home_win, draw, away_win, over, under,
    both_teams_score, team_over, exact_score, clean_sheet,
    home_spread, away_spread,
)


def _indep_matrix(lam, mu):
    return score_matrix(lam, mu, rho=0.0, max_goals=10)


def test_moneyline_partitions_probability():
    M = _indep_matrix(1.6, 1.1)
    h = price_predicate(M, home_win)
    d = price_predicate(M, draw)
    a = price_predicate(M, away_win)
    assert round(h + d + a, 6) == 1.0
    assert h > a  # stronger home side


def test_over_under_are_complementary():
    M = _indep_matrix(1.4, 1.3)
    assert round(price_predicate(M, over(2.5)) + price_predicate(M, under(2.5)), 6) == 1.0


def test_over_line_matches_manual_tail():
    M = _indep_matrix(1.2, 1.0)
    # total >= 3
    manual = sum(M[x][y] for x in range(len(M)) for y in range(len(M)) if x + y >= 3)
    assert abs(price_predicate(M, over(2.5)) - manual) < 1e-9


def test_btts_matches_manual():
    M = _indep_matrix(1.5, 1.5)
    manual = sum(M[x][y] for x in range(1, len(M)) for y in range(1, len(M)))
    assert abs(price_predicate(M, both_teams_score) - manual) < 1e-9


def test_team_over_and_clean_sheet():
    M = _indep_matrix(2.0, 0.4)
    # home over 1.5 => home scores >= 2
    manual = sum(M[x][y] for x in range(2, len(M)) for y in range(len(M)))
    assert abs(price_predicate(M, team_over("home", 1.5)) - manual) < 1e-9
    # away clean sheet => home scores 0
    cs = sum(M[0][y] for y in range(len(M)))
    assert abs(price_predicate(M, clean_sheet("away")) - cs) < 1e-9


def test_spread_matches_margin_tail():
    M = _indep_matrix(2.0, 0.8)
    # home wins by more than 1.5 => x - y >= 2
    manual = sum(M[x][y] for x in range(len(M)) for y in range(len(M)) if x - y >= 2)
    assert abs(price_predicate(M, home_spread(1.5)) - manual) < 1e-9
    # away spread is the mirror
    away_manual = sum(M[x][y] for x in range(len(M)) for y in range(len(M)) if y - x >= 2)
    assert abs(price_predicate(M, away_spread(1.5)) - away_manual) < 1e-9
    # stronger home => home spread more likely than away spread
    assert price_predicate(M, home_spread(1.5)) > price_predicate(M, away_spread(1.5))


def test_exact_score_reads_one_cell():
    M = _indep_matrix(1.3, 1.1)
    assert abs(price_predicate(M, exact_score(2, 1)) - M[2][1]) < 1e-12


def test_unknown_side_raises():
    with pytest.raises(ValueError):
        team_over("middle", 1.5)
