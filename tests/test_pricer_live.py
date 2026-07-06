import os
import pytest
from kalshi_edge.data.cache import connect
from kalshi_edge.model.goal_model import GoalModel
from kalshi_edge.pricer.price_match import price_match

DB = "data/football.sqlite"


@pytest.mark.live
def test_price_match_on_real_matchup():
    if not os.path.exists(DB):
        pytest.skip("run scripts/build_db.py first")
    model = GoalModel.from_db(connect(DB), ref_date="2026-07-03", since="2016-01-01")
    prices = price_match(model, "Egypt", "Australia", neutral=True)
    ml = prices["moneyline"]
    assert round(ml["home"] + ml["draw"] + ml["away"], 6) == 1.0
    # Totals must be monotone: P(over 0.5) >= P(over 1.5) >= P(over 2.5)
    overs = [prices["totals"][ln]["over"] for ln in (0.5, 1.5, 2.5)]
    assert overs[0] >= overs[1] >= overs[2]
