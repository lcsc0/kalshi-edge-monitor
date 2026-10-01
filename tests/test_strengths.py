from kalshi_edge.data.cache import connect
from kalshi_edge.data.intl_results import load_results_csv
from kalshi_edge.model.strengths import decay_weight, team_strengths


def test_decay_weight_halves_at_half_life():
    assert decay_weight("2026-01-01", "2026-01-01", 730.0) == 1.0
    assert round(decay_weight("2024-01-02", "2026-01-01", 730.0), 3) == 0.5  # ~730 days
    assert decay_weight("2027-01-01", "2026-01-01", 730.0) == 0.0  # future -> 0


def test_team_strengths_ranks_dominant_team_higher():
    rows = "date,home_team,away_team,home_score,away_score,tournament,city,country,neutral\n"
    for i in range(10):
        rows += f"2025-0{i%9+1}-01,Strong,Weak,4,0,Friendly,X,Y,TRUE\n"
        rows += f"2025-0{i%9+1}-15,Weak,Strong,0,3,Friendly,X,Y,TRUE\n"
    conn = connect(); load_results_csv(conn, rows)
    s = team_strengths(conn, ref_date="2025-10-01")
    assert s["mu"] > 0
    assert s["teams"]["Strong"]["attack"] > s["teams"]["Weak"]["attack"]
    assert s["teams"]["Strong"]["defense"] < s["teams"]["Weak"]["defense"]


def test_home_factor_reflects_home_scoring_edge():
    rows = "date,home_team,away_team,home_score,away_score,tournament,city,country,neutral\n"
    for i in range(8):
        rows += f"2025-0{i%8+1}-01,A,B,2,1,Friendly,X,Y,FALSE\n"
    conn = connect(); load_results_csv(conn, rows)
    s = team_strengths(conn, ref_date="2025-09-01")
    assert s["home_factor"] > 1.0


def test_before_cutoff_excludes_later_matches():
    rows = "date,home_team,away_team,home_score,away_score,tournament,city,country,neutral\n"
    rows += "2020-01-01,A,B,5,0,Friendly,X,Y,TRUE\n"   # before cutoff
    rows += "2025-01-01,A,B,0,5,Friendly,X,Y,TRUE\n"   # after cutoff (must be ignored)
    conn = connect(); load_results_csv(conn, rows)
    s = team_strengths(conn, ref_date="2021-01-01", before="2021-01-01")
    # Only the 5-0 match counts, so A's attack must exceed its defense.
    assert s["teams"]["A"]["attack"] > s["teams"]["A"]["defense"]
