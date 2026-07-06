from kalshi_edge.data.cache import connect
from kalshi_edge.data.intl_results import load_results_csv, load_goalscorers_csv
from kalshi_edge.model.goal_model import GoalModel
from kalshi_edge.enrich.analysis import build_analysis

ROWS = "date,home_team,away_team,home_score,away_score,tournament,city,country,neutral\n" + "".join(
    f"2025-0{i%9+1}-01,Portugal,Spain,2,1,Friendly,X,Y,TRUE\n"
    f"2025-0{i%9+1}-15,Spain,Portugal,1,2,Friendly,X,Y,TRUE\n" for i in range(6))
GOALS = "date,home_team,away_team,team,scorer,minute,own_goal,penalty\n" + "".join(
    f"2025-0{i%9+1}-01,Portugal,Spain,Portugal,Ronaldo,10,FALSE,FALSE\n" for i in range(6))


def test_build_analysis_combines_model_form_and_scorers():
    conn = connect(); load_results_csv(conn, ROWS); load_goalscorers_csv(conn, GOALS)
    model = GoalModel.from_db(conn, ref_date="2025-10-01")
    a = build_analysis(conn, model, "Portugal", "Spain", neutral=True)
    assert set(a["outcome_probs"]) == {"home", "draw", "away"}
    assert "form" in a and "Portugal" in a["form"] and len(a["form"]["Portugal"]) > 0
    assert a["top_scorers"]["Portugal"][0]["scorer"] == "Ronaldo"
    assert "top_props" in a
    assert a["coaches"] == {"Portugal": None, "Spain": None}
