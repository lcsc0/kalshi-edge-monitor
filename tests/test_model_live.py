import os
import pytest
from kalshi_edge.data.cache import connect
from kalshi_edge.model.goal_model import GoalModel

DB = "data/football.sqlite"


@pytest.mark.live
def test_model_favors_strong_side_on_real_data():
    if not os.path.exists(DB):
        pytest.skip("run scripts/build_db.py first")
    model = GoalModel.from_db(connect(DB), ref_date="2026-07-03", since="2016-01-01")
    # Argentina should be a heavy favorite over Cape Verde on neutral ground.
    p = model.match_probabilities("Argentina", "Cape Verde", neutral=True)
    assert p["home"] > 0.6
    assert p["home"] > p["away"] > 0
