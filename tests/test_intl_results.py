from kalshi_edge.data.cache import connect
from kalshi_edge.data.intl_results import (
    load_results_csv, team_matches, team_goal_rates,
)

RESULTS = (
    "date,home_team,away_team,home_score,away_score,tournament,city,country,neutral\n"
    "2026-06-01,Brazil,Chile,3,1,Friendly,Rio,Brazil,FALSE\n"
    "2026-06-05,Argentina,Brazil,2,2,Friendly,Buenos Aires,Argentina,FALSE\n"
    "2026-06-09,Brazil,Peru,0,1,Friendly,Sao Paulo,Brazil,TRUE\n"
)


def test_load_results_inserts_rows_and_records_meta():
    conn = connect()
    n = load_results_csv(conn, RESULTS)
    assert n == 3
    assert conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 3
    meta = conn.execute("SELECT row_count FROM source_meta WHERE source='results'").fetchone()
    assert meta[0] == 3


def test_team_matches_filters_and_orders():
    conn = connect(); load_results_csv(conn, RESULTS)
    ms = team_matches(conn, "Brazil")
    assert [m["date"] for m in ms] == ["2026-06-01", "2026-06-05", "2026-06-09"]
    assert team_matches(conn, "Brazil", since="2026-06-04")[0]["date"] == "2026-06-05"


def test_team_goal_rates_averages_scored_and_conceded():
    conn = connect(); load_results_csv(conn, RESULTS)
    # Brazil scored 3,2,0 = 5/3 ; conceded 1,2,1 = 4/3
    scored, conceded = team_goal_rates(conn, "Brazil")
    assert round(scored, 4) == round(5 / 3, 4)
    assert round(conceded, 4) == round(4 / 3, 4)
