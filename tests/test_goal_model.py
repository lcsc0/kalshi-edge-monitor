import pytest
from kalshi_edge.data.cache import connect
from kalshi_edge.data.intl_results import load_results_csv
from kalshi_edge.model.goal_model import GoalModel

ROWS = "date,home_team,away_team,home_score,away_score,tournament,city,country,neutral\n" + "".join(
    f"2025-0{i%9+1}-01,Strong,Weak,3,0,Friendly,X,Y,TRUE\n"
    f"2025-0{i%9+1}-15,Weak,Strong,0,3,Friendly,X,Y,TRUE\n" for i in range(10))


def _model():
    conn = connect(); load_results_csv(conn, ROWS)
    return GoalModel.from_db(conn, ref_date="2025-10-01")


def test_joint_matrix_sums_to_one():
    M = _model().joint_matrix("Strong", "Weak", neutral=True)
    assert round(sum(sum(r) for r in M), 6) == 1.0


def test_strong_team_favored():
    p = _model().match_probabilities("Strong", "Weak", neutral=True)
    assert p["home"] > 0.6 and p["home"] > p["away"]


def test_analysis_record_has_drivers():
    a = _model().analysis("Strong", "Weak", neutral=True)
    assert a["expected_goals"]["home"] > a["expected_goals"]["away"]
    assert "Strong" in a["strength"] and "Weak" in a["strength"]
    assert set(a["outcome_probs"]) == {"home", "draw", "away"}


def test_unknown_team_raises():
    with pytest.raises(ValueError):
        _model().expected_goals("Strong", "Nonexistent", neutral=True)
