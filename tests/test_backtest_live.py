import os
import pytest
from kalshi_edge.data.cache import connect
from kalshi_edge.backtest.runner import backtest_outcomes
from kalshi_edge.backtest.metrics import brier_score, baseline_brier

DB = "data/football.sqlite"


@pytest.mark.live
def test_model_has_skill_over_baseline_on_real_history():
    if not os.path.exists(DB):
        pytest.skip("run scripts/build_db.py first")
    recs = backtest_outcomes(connect(DB), test_start="2023-01-01", test_end="2023-06-30",
                             since="2015-01-01")
    assert len(recs) > 100
    # The model should beat the climatology baseline (lower Brier = better).
    assert brier_score(recs) < baseline_brier(recs)
