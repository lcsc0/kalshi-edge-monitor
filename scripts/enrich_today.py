from datetime import datetime, timezone
from kalshi_edge.config import load_env
from kalshi_edge.data.cache import connect
from kalshi_edge.model.goal_model import GoalModel
from kalshi_edge.enrich.apifootball import ApiFootball
from kalshi_edge.enrich.analysis import build_analysis

DB = "data/football.sqlite"


def main(home: str, away: str) -> None:
    load_env()
    conn = connect(DB)
    model = GoalModel.from_db(conn, ref_date=str(datetime.now(timezone.utc).date()),
                              since="2016-01-01")
    api = ApiFootball(conn=conn)
    # Recency window so scorers/props reflect current players, not all-time legends.
    # (Confirmed-XI presence filtering is a later refinement.)
    since = f"{datetime.now(timezone.utc).year - 3}-01-01"
    a = build_analysis(conn, model, home, away, neutral=True, api=api, since=since)
    p = a["outcome_probs"]
    print(f"{home} vs {away}  ({a['expected_goals']['home']:.2f}-{a['expected_goals']['away']:.2f} xG)")
    print(f"  win prob : {home} {p['home']:.3f} | draw {p['draw']:.3f} | {away} {p['away']:.3f}")
    print(f"  coaches  : {a['coaches']}")
    for team in (home, away):
        form = "".join(f["result"] for f in a["form"][team][:5])
        print(f"  {team} form (recent->old): {form}")
    print("  top score props:")
    for pr in a["top_props"][:6]:
        print(f"    {pr['scorer']:<20} ({pr['team']}) P(scores)={pr['score_prob']:.3f}")


if __name__ == "__main__":
    import sys
    main(sys.argv[1], sys.argv[2])
