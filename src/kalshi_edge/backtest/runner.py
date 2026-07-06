from kalshi_edge.model.goal_model import GoalModel


def _outcome(home_score: int, away_score: int) -> str:
    if home_score > away_score:
        return "home"
    if home_score == away_score:
        return "draw"
    return "away"


def backtest_outcomes(conn, test_start: str, test_end: str,
                      since: str | None = None,
                      half_life_days: float = 730.0) -> list[dict]:
    """Walk forward over completed matches in [test_start, test_end], predicting each
    with a model built strictly from earlier data (before=match date). Returns records."""
    query = ("SELECT date, home_team, away_team, home_score, away_score, neutral "
             "FROM matches WHERE date >= ? AND date <= ? "
             "AND home_score IS NOT NULL AND away_score IS NOT NULL ORDER BY date")
    records = []
    for m in conn.execute(query, (test_start, test_end)).fetchall():
        try:
            model = GoalModel.from_db(conn, ref_date=m["date"], since=since, before=m["date"])
            probs = model.match_probabilities(m["home_team"], m["away_team"],
                                              neutral=bool(m["neutral"]))
        except (ValueError, ZeroDivisionError):
            continue  # team without prior history
        records.append({
            "date": m["date"],
            "probs": probs,
            "outcome": _outcome(m["home_score"], m["away_score"]),
        })
    return records
