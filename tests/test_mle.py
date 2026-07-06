from kalshi_edge.data.cache import connect
from kalshi_edge.data.intl_results import load_results_csv
from kalshi_edge.model.mle import fit_dixon_coles

ROWS = "date,home_team,away_team,home_score,away_score,tournament,city,country,neutral\n" + "".join(
    f"2022-{mo:02d}-01,Strong,Weak,3,0,Friendly,X,Y,TRUE\n"
    f"2022-{mo:02d}-08,Strong,Mid,2,0,Friendly,X,Y,TRUE\n"
    f"2022-{mo:02d}-15,Mid,Weak,2,1,Friendly,X,Y,TRUE\n"
    f"2022-{mo:02d}-22,Weak,Mid,0,1,Friendly,X,Y,FALSE\n"
    for mo in range(1, 13))


def test_fit_recovers_team_ordering_and_globals():
    conn = connect(); load_results_csv(conn, ROWS)
    fit = fit_dixon_coles(conn, ref_date="2023-01-01", since="2020-01-01", min_games=5)
    assert fit.attack["Strong"] > fit.attack["Mid"] > fit.attack["Weak"]
    assert fit.defense["Strong"] > fit.defense["Weak"]
    assert 0.0 <= fit.home_adv <= 1.0
    assert -0.2 <= fit.rho <= 0.2
    assert abs(sum(fit.attack.values())) < 1e-6


def test_fit_only_includes_teams_meeting_min_games():
    conn = connect(); load_results_csv(conn, ROWS)
    fit = fit_dixon_coles(conn, ref_date="2023-01-01", since="2020-01-01", min_games=1000)
    assert fit.attack == {}
