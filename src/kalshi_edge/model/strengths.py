from datetime import date as _date

DEFAULT_HALF_LIFE_DAYS = 730.0


def decay_weight(match_date: str, ref_date: str,
                 half_life_days: float = DEFAULT_HALF_LIFE_DAYS) -> float:
    age = (_date.fromisoformat(ref_date[:10]) - _date.fromisoformat(match_date[:10])).days
    if age < 0:
        return 0.0
    return 0.5 ** (age / half_life_days)


def team_strengths(conn, ref_date: str,
                   half_life_days: float = DEFAULT_HALF_LIFE_DAYS,
                   since: str | None = None,
                   before: str | None = None) -> dict:
    """Time-weighted attack/defense ratings (relative to league mean `mu`) + home factor.

    attack = (weighted goals scored per match) / mu
    defense = (weighted goals conceded per match) / mu   (lower = stronger defense)
    home_factor = sqrt(weighted home goals / weighted away goals) over non-neutral games
    """
    query = ("SELECT date, home_team, away_team, home_score, away_score, neutral "
             "FROM matches WHERE home_score IS NOT NULL AND away_score IS NOT NULL")
    args: list = []
    if since:
        query += " AND date >= ?"
        args.append(since)
    if before:
        query += " AND date < ?"
        args.append(before)

    gs: dict = {}
    gc: dict = {}
    w: dict = {}
    tot_goals = tot_team_matches = 0.0
    home_goals_w = away_goals_w = 0.0

    for r in conn.execute(query, args).fetchall():
        wt = decay_weight(r["date"], ref_date, half_life_days)
        if wt <= 0:
            continue
        h, a, hs, as_ = r["home_team"], r["away_team"], r["home_score"], r["away_score"]
        for team, scored, conceded in ((h, hs, as_), (a, as_, hs)):
            gs[team] = gs.get(team, 0.0) + wt * scored
            gc[team] = gc.get(team, 0.0) + wt * conceded
            w[team] = w.get(team, 0.0) + wt
        tot_goals += wt * (hs + as_)
        tot_team_matches += wt * 2
        if not r["neutral"]:
            home_goals_w += wt * hs
            away_goals_w += wt * as_

    mu = tot_goals / tot_team_matches if tot_team_matches else 0.0
    home_factor = (home_goals_w / away_goals_w) ** 0.5 if away_goals_w > 0 else 1.0
    teams = {
        team: {
            "attack": (gs[team] / w[team]) / mu if mu else 0.0,
            "defense": (gc[team] / w[team]) / mu if mu else 0.0,
            "weight": w[team],
        }
        for team in w if w[team] > 0
    }
    return {"mu": mu, "home_factor": home_factor, "teams": teams}
