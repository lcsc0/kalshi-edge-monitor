import math
from kalshi_edge.model.poisson import dc_tau, score_matrix, outcome_probs


def test_dc_tau_four_cells_and_default():
    lam, mu, rho = 1.3, 1.1, -0.1
    assert dc_tau(0, 0, lam, mu, rho) == 1 - lam * mu * rho
    assert dc_tau(0, 1, lam, mu, rho) == 1 + lam * rho
    assert dc_tau(1, 0, lam, mu, rho) == 1 + mu * rho
    assert dc_tau(1, 1, lam, mu, rho) == 1 - rho
    assert dc_tau(2, 3, lam, mu, rho) == 1.0  # outside the correction


def test_score_matrix_sums_to_one_and_is_independent_when_rho_zero():
    lam, mu = 1.4, 1.0
    M = score_matrix(lam, mu, rho=0.0, max_goals=10)
    total = sum(sum(row) for row in M)
    assert round(total, 6) == 1.0
    pois = lambda k, m: math.exp(-m) * m ** k / math.factorial(k)
    assert abs(M[1][2] - pois(1, lam) * pois(2, mu)) < 1e-4


def test_outcome_probs_symmetric_when_equal_rates():
    probs = outcome_probs(score_matrix(1.2, 1.2, rho=0.0))
    assert round(probs["home"], 6) == round(probs["away"], 6)
    assert round(probs["home"] + probs["draw"] + probs["away"], 6) == 1.0


def test_stronger_side_has_higher_win_prob():
    probs = outcome_probs(score_matrix(2.2, 0.7, rho=0.0))
    assert probs["home"] > probs["away"]
