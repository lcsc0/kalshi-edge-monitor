from kalshi_edge.data.cache import connect
from kalshi_edge.data.intl_results import load_results_csv
from kalshi_edge.backtest.runner import backtest_outcomes

ROWS = "date,home_team,away_team,home_score,away_score,tournament,city,country,neutral\n" + "".join(
    f"20{y}-0{m+1}-01,Strong,Weak,3,0,Friendly,X,Y,TRUE\n" for y in (20, 21, 22) for m in range(6)
) + "2023-01-10,Strong,Weak,2,0,Friendly,X,Y,TRUE\n2023-02-10,Weak,Strong,0,2,Friendly,X,Y,TRUE\n"


def test_backtest_outcomes_records_predictions_without_lookahead():
    conn = connect(); load_results_csv(conn, ROWS)
    recs = backtest_outcomes(conn, test_start="2023-01-01", test_end="2023-12-31", since="2018-01-01")
    assert len(recs) == 2
    assert recs[0]["outcome"] == "home"   # 2023-01-10 Strong home win
    assert recs[1]["outcome"] == "away"   # 2023-02-10 Strong away win
    assert recs[0]["probs"]["home"] > recs[0]["probs"]["away"]
    assert recs[1]["probs"]["away"] > recs[1]["probs"]["home"]


def test_backtest_skips_matches_with_no_prior_history():
    conn = connect(); load_results_csv(conn, ROWS)
    recs = backtest_outcomes(conn, test_start="2019-01-01", test_end="2019-12-31", since="2018-01-01")
    assert recs == []
