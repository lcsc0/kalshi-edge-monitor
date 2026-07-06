from kalshi_edge.data.cache import connect
from kalshi_edge.data.intl_results import load_results_csv, load_goalscorers_csv
from kalshi_edge.enrich.form import recent_form, top_scorers

RESULTS = (
    "date,home_team,away_team,home_score,away_score,tournament,city,country,neutral\n"
    "2025-01-01,Portugal,A,2,0,Friendly,X,Y,TRUE\n"
    "2025-02-01,B,Portugal,1,1,Friendly,X,Y,TRUE\n"
    "2025-03-01,Portugal,C,0,3,Friendly,X,Y,TRUE\n"
)
GOALS = (
    "date,home_team,away_team,team,scorer,minute,own_goal,penalty\n"
    "2025-01-01,Portugal,A,Portugal,Ronaldo,10,FALSE,FALSE\n"
    "2025-01-01,Portugal,A,Portugal,Ronaldo,20,FALSE,FALSE\n"
    "2025-02-01,B,Portugal,Portugal,Silva,30,FALSE,FALSE\n"
)


def test_recent_form_returns_last_n_results_newest_first():
    conn = connect(); load_results_csv(conn, RESULTS)
    form = recent_form(conn, "Portugal", n=3)
    assert [f["result"] for f in form] == ["L", "D", "W"]
    assert form[0]["date"] == "2025-03-01"
    assert form[0]["goals_for"] == 0 and form[0]["goals_against"] == 3


def test_top_scorers_ranked_by_goals():
    conn = connect(); load_goalscorers_csv(conn, GOALS)
    scorers = top_scorers(conn, "Portugal", limit=5)
    assert scorers[0]["scorer"] == "Ronaldo" and scorers[0]["goals"] == 2
    assert scorers[1]["scorer"] == "Silva" and scorers[1]["goals"] == 1
