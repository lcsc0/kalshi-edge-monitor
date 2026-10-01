from kalshi_edge.data.cache import connect
from kalshi_edge.data.club_results import load_club_csv, season_codes

CSV = """﻿Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG
E0,24/05/2026,16:00,Liverpool,Brentford,2,1
E0,31/12/2025,15:00,Arsenal,Chelsea,,
E0,01/08/25,20:00,Man City,Spurs,3,0
"""


def test_season_codes():
    assert season_codes(2019, 2021) == ["1920", "2021", "2122"]


def test_load_skips_unplayed_and_handles_two_digit_year():
    conn = connect()
    assert load_club_csv(conn, CSV, "E0") == 2
    rows = conn.execute("SELECT date, home_team, neutral, tournament FROM matches ORDER BY date").fetchall()
    assert [(r["date"], r["home_team"], r["neutral"], r["tournament"]) for r in rows] == [
        ("2025-08-01", "Man City", 0, "EPL"), ("2026-05-24", "Liverpool", 0, "EPL")]


def test_kickoff_converted_from_uk_local_to_utc():
    conn = connect()
    load_club_csv(conn, CSV, "E0")
    # 2026-05-24 16:00 BST == 15:00 UTC
    ts = conn.execute("SELECT kickoff_utc FROM kickoffs WHERE home_team='Liverpool'").fetchone()[0]
    assert ts == 1779634800
