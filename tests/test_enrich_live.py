import os
import pytest
from kalshi_edge.config import load_env
from kalshi_edge.data.cache import connect
from kalshi_edge.enrich.apifootball import ApiFootball
from kalshi_edge.enrich.teams import resolve_team_id

DB = "data/football.sqlite"


@pytest.mark.live
def test_resolve_real_national_team_id():
    load_env()
    if not os.environ.get("API_FOOTBALL_KEY"):
        pytest.skip("no API_FOOTBALL_KEY")
    api = ApiFootball(conn=connect(DB) if os.path.exists(DB) else connect())
    assert resolve_team_id(api, "Portugal") == 27  # national side
