"""Statistical lineup adjustment: missing regular starters -> goal-rate multipliers.

Every number here is an UNVALIDATED PRIOR. The paper test exists to find out whether it
beats the unadjusted model and the market; nothing is fitted to data.

For each regular starter (weight = how often he started recently) who is not in the XI:
  * attacking positions cut the team's own expected goals,
  * defensive positions (GK most) raise the opponent's expected goals.
Per-team effects are capped so one bad lineup can't swing a price wildly.
"""
ATTACK_EFFECT = {"F": 0.05, "M": 0.02, "D": 0.0, "G": 0.0}    # own-goals reduction per missing regular
DEFENCE_EFFECT = {"G": 0.06, "D": 0.03, "M": 0.01, "F": 0.0}  # opponent-goals increase per missing regular
TEAM_CAP = 0.20


def team_effects(missing: list[dict]) -> tuple[float, float]:
    """-> (own_attack_mult, opponent_goals_mult) for one team's missing regulars."""
    att = sum(ATTACK_EFFECT.get(m["pos"], 0.0) * m["share"] for m in missing)
    dfn = sum(DEFENCE_EFFECT.get(m["pos"], 0.0) * m["share"] for m in missing)
    return 1.0 - min(att, TEAM_CAP), 1.0 + min(dfn, TEAM_CAP)


def goal_multipliers(home_missing: list[dict], away_missing: list[dict]) -> tuple[float, float]:
    """-> (home_goals_mult, away_goals_mult) applied to the model's expected goals."""
    h_att, h_conc = team_effects(home_missing)
    a_att, a_conc = team_effects(away_missing)
    return h_att * a_conc, a_att * h_conc
