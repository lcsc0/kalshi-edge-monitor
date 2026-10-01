import pytest
from kalshi_edge.data.cache import connect
from kalshi_edge.data.intl_results import load_results_csv
from kalshi_edge.model.mle_model import MLEGoalModel
from tests.test_mle import ROWS


def _model():
    conn = connect(); load_results_csv(conn, ROWS)
    return MLEGoalModel.from_db(conn, ref_date="2023-01-01", since="2020-01-01", min_games=5)


def test_joint_matrix_sums_to_one():
    M = _model().joint_matrix("Strong", "Weak", neutral=True)
    assert round(sum(sum(r) for r in M), 6) == 1.0


def test_strong_favored_over_weak():
    p = _model().match_probabilities("Strong", "Weak", neutral=True)
    assert p["home"] > 0.5 and p["home"] > p["away"]


def test_home_advantage_helps_home_side():
    m = _model()
    ph = m.match_probabilities("Mid", "Strong", neutral=False)["home"]
    pn = m.match_probabilities("Mid", "Strong", neutral=True)["home"]
    assert ph > pn


def test_analysis_shape_matches_goalmodel():
    a = _model().analysis("Strong", "Weak", neutral=True)
    assert set(a["outcome_probs"]) == {"home", "draw", "away"}
    assert a["expected_goals"]["home"] > a["expected_goals"]["away"]
    assert "Strong" in a["strength"]


def test_unknown_team_raises():
    with pytest.raises(ValueError):
        _model().expected_goals("Strong", "Nobody", neutral=True)
