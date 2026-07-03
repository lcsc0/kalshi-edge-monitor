import pytest
from kalshi_edge.data.cache import connect
from kalshi_edge.data.sources import download_text
from kalshi_edge.data.intl_results import RESULTS_URL, load_results_csv, team_goal_rates


@pytest.mark.live
def test_live_results_download_and_query():
    conn = connect()
    n = load_results_csv(conn, download_text(RESULTS_URL))
    assert n > 40000  # dataset has ~49.5k rows
    scored, conceded = team_goal_rates(conn, "Brazil", since="2015-01-01")
    assert scored > 0 and conceded >= 0
