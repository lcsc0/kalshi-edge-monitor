import os
import pytest
from kalshi_edge.data.cache import connect
from kalshi_edge.model.goal_model import GoalModel
from kalshi_edge.model.mle_model import MLEGoalModel
from kalshi_edge.backtest.metrics import brier_score

DB = "data/football.sqlite"


def _score(model, rows, idx_ok):
    recs = []
    for r in rows:
        h, a = r["home_team"], r["away_team"]
        if not idx_ok(h, a):
            continue
        y = "home" if r["home_score"] > r["away_score"] else ("draw" if r["home_score"] == r["away_score"] else "away")
        recs.append({"probs": model.match_probabilities(h, a, neutral=bool(r["neutral"])),
                     "outcome": y})
    return recs


@pytest.mark.live
def test_mle_beats_v1_out_of_sample():
    if not os.path.exists(DB):
        pytest.skip("run scripts/build_db.py first")
    conn = connect(DB)
    ref = "2023-01-01"
    mle = MLEGoalModel.from_db(conn, ref_date=ref, since="2014-01-01")
    v1 = GoalModel.from_db(conn, ref_date=ref, since="2014-01-01", before=ref)
    test = conn.execute(
        "SELECT home_team,away_team,home_score,away_score,neutral FROM matches "
        "WHERE date>=? AND date<=? AND home_score IS NOT NULL", (ref, "2023-12-31")).fetchall()
    ok = lambda h, a: h in mle.fit.attack and a in mle.fit.attack
    mle_recs = _score(mle, test, ok)
    v1_recs = _score(v1, test, ok)
    assert len(mle_recs) > 100
    assert brier_score(mle_recs) < brier_score(v1_recs)
