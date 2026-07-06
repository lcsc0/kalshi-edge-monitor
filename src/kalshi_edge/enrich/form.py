def recent_form(conn, team: str, n: int = 5, before: str | None = None) -> list[dict]:
    """Last `n` completed matches for team, newest first, each with W/D/L + goals."""
    query = ("SELECT date, home_team, away_team, home_score, away_score FROM matches "
             "WHERE (home_team = ? OR away_team = ?) "
             "AND home_score IS NOT NULL AND away_score IS NOT NULL")
    args = [team, team]
    if before:
        query += " AND date < ?"
        args.append(before)
    query += " ORDER BY date DESC LIMIT ?"
    args.append(n)
    out = []
    for r in conn.execute(query, args).fetchall():
        if r["home_team"] == team:
            gf, ga = r["home_score"], r["away_score"]
            opp = r["away_team"]
        else:
            gf, ga = r["away_score"], r["home_score"]
            opp = r["home_team"]
        result = "W" if gf > ga else ("D" if gf == ga else "L")
        out.append({"date": r["date"], "opponent": opp, "goals_for": gf,
                    "goals_against": ga, "result": result})
    return out


def top_scorers(conn, team: str, limit: int = 5, since: str | None = None) -> list[dict]:
    """Most prolific scorers for the team (non-own goals) over the window."""
    query = ("SELECT scorer, COUNT(*) AS goals FROM goals "
             "WHERE team = ? AND own_goal = 0")
    args = [team]
    if since:
        query += " AND date >= ?"
        args.append(since)
    query += " GROUP BY scorer ORDER BY goals DESC, scorer LIMIT ?"
    args.append(limit)
    return [{"scorer": r["scorer"], "goals": r["goals"]}
            for r in conn.execute(query, args).fetchall()]
