from kalshi_edge.pricer.prices import (
    moneyline, total_over, total_under, team_total_over, btts, spread_cover,
)

DEFAULT_TOTAL_LINES = [0.5, 1.5, 2.5, 3.5, 4.5, 5.5]
DEFAULT_TEAM_TOTAL_LINES = [0.5, 1.5, 2.5]
DEFAULT_SPREAD_LINES = [1.5, 2.5]


def price_match(model, home: str, away: str, neutral: bool = True,
                total_lines: list[float] | None = None,
                team_total_lines: list[float] | None = None,
                spread_lines: list[float] | None = None) -> dict:
    """Fair probabilities for all supported Kalshi contract types on this matchup."""
    total_lines = DEFAULT_TOTAL_LINES if total_lines is None else total_lines
    team_total_lines = DEFAULT_TEAM_TOTAL_LINES if team_total_lines is None else team_total_lines
    spread_lines = DEFAULT_SPREAD_LINES if spread_lines is None else spread_lines

    m = model.joint_matrix(home, away, neutral)
    return {
        "moneyline": moneyline(m),
        "totals": {ln: {"over": total_over(m, ln), "under": total_under(m, ln)}
                   for ln in total_lines},
        "team_totals": {
            "home": {ln: team_total_over(m, ln, "home") for ln in team_total_lines},
            "away": {ln: team_total_over(m, ln, "away") for ln in team_total_lines},
        },
        "btts": btts(m),
        "spreads": {
            "home": {ln: spread_cover(m, ln, "home") for ln in spread_lines},
            "away": {ln: spread_cover(m, ln, "away") for ln in spread_lines},
        },
    }
