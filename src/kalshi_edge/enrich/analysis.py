from kalshi_edge.enrich.form import recent_form, top_scorers
from kalshi_edge.enrich.teams import resolve_team_id
from kalshi_edge.pricer.players import player_goal_share, player_score_prob


def _coach(api, team: str):
    if api is None:
        return None
    team_id = resolve_team_id(api, team)
    if team_id is None:
        return None
    coaches = api.get("/coachs", {"team": str(team_id)})
    return coaches[0].get("name") if coaches else None


def build_analysis(conn, model, home: str, away: str, neutral: bool = True,
                   api=None, since: str | None = None) -> dict:
    base = model.analysis(home, away, neutral)
    lam, mu = base["expected_goals"]["home"], base["expected_goals"]["away"]
    props = []
    for team, team_xg in ((home, lam), (away, mu)):
        for sc in top_scorers(conn, team, limit=3, since=since):
            share = player_goal_share(conn, sc["scorer"], team, since)
            props.append({"team": team, "scorer": sc["scorer"],
                          "score_prob": player_score_prob(share, team_xg)})
    props.sort(key=lambda p: p["score_prob"], reverse=True)
    return {
        **base,
        "form": {home: recent_form(conn, home), away: recent_form(conn, away)},
        "top_scorers": {home: top_scorers(conn, home), away: top_scorers(conn, away)},
        "coaches": {home: _coach(api, home), away: _coach(api, away)},
        "top_props": props,
    }
