from kalshi_edge.data.cache import connect
from kalshi_edge.data.intl_results import load_results_csv
from kalshi_edge.model.goal_model import GoalModel
from kalshi_edge.pricer.price_match import price_match

ROWS = "date,home_team,away_team,home_score,away_score,tournament,city,country,neutral\n" + "".join(
    f"2025-0{i%9+1}-01,Strong,Weak,3,0,Friendly,X,Y,TRUE\n"
    f"2025-0{i%9+1}-15,Weak,Strong,0,3,Friendly,X,Y,TRUE\n" for i in range(10))


def test_price_match_returns_all_markets():
    conn = connect(); load_results_csv(conn, ROWS)
    model = GoalModel.from_db(conn, ref_date="2025-10-01")
    prices = price_match(model, "Strong", "Weak", neutral=True,
                         total_lines=[2.5], spread_lines=[1.5])
    ml = prices["moneyline"]
    assert round(ml["home"] + ml["draw"] + ml["away"], 6) == 1.0
    assert ml["home"] > ml["away"]
    o = prices["totals"][2.5]
    assert round(o["over"] + o["under"], 6) == 1.0
    assert 0.0 <= prices["btts"] <= 1.0
    assert "home" in prices["team_totals"] and "away" in prices["team_totals"]
    assert 2.5 in prices["team_totals"]["home"]
    assert 1.5 in prices["spreads"]["home"]
