import sys
from kalshi_edge.data.cache import connect
from kalshi_edge.model.goal_model import GoalModel
from kalshi_edge.model.mle_model import MLEGoalModel
from kalshi_edge.backtest.metrics import brier_score, baseline_brier, accuracy

DB = "data/football.sqlite"


def _recs(model, rows, ok):
    out = []
    for r in rows:
        h, a = r["home_team"], r["away_team"]
        if not ok(h, a):
            continue
        y = "home" if r["home_score"] > r["away_score"] else ("draw" if r["home_score"] == r["away_score"] else "away")
        out.append({"probs": model.match_probabilities(h, a, neutral=bool(r["neutral"])), "outcome": y})
    return out


def main() -> None:
    ref = sys.argv[1] if len(sys.argv) > 1 else "2023-01-01"
    end = sys.argv[2] if len(sys.argv) > 2 else "2024-12-31"
    conn = connect(DB)
    mle = MLEGoalModel.from_db(conn, ref_date=ref, since="2014-01-01")
    v1 = GoalModel.from_db(conn, ref_date=ref, since="2014-01-01", before=ref)
    rows = conn.execute("SELECT home_team,away_team,home_score,away_score,neutral FROM matches "
                        "WHERE date>=? AND date<=? AND home_score IS NOT NULL", (ref, end)).fetchall()
    ok = lambda h, a: h in mle.fit.attack and a in mle.fit.attack
    mr, vr = _recs(mle, rows, ok), _recs(v1, rows, ok)
    print(f"Backtest {ref}..{end} (fit-once): {len(mr)} matches")
    print(f"  baseline Brier : {baseline_brier(mr):.4f}")
    print(f"  v1  Brier      : {brier_score(vr):.4f}  acc {accuracy(vr):.3f}")
    print(f"  MLE Brier      : {brier_score(mr):.4f}  acc {accuracy(mr):.3f}")


if __name__ == "__main__":
    main()
