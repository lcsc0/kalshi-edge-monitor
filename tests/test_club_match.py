from datetime import date

from kalshi_edge.data.cache import connect
from kalshi_edge.kalshi.club_match import (
    event_date, event_suffix, name_score, resolve_event, title_teams)
from kalshi_edge.kalshi.market_parse import parse_contract


def test_event_date_and_suffix():
    assert event_date("KXEPLGAME-26MAY24LFCBRE") == date(2026, 5, 24)
    assert event_suffix("KXEPLTOTAL-26MAY24BRIMUN") == "26MAY24BRIMUN"
    assert event_date("garbage") is None


def test_title_teams():
    assert title_teams("Villarreal vs Atletico Winner?") == ("Villarreal", "Atletico")
    assert title_teams("Will over 4.5 goals be scored?") is None


def test_name_scores():
    assert name_score("Atletico", "Atletico Madrid") >= 0.85
    assert name_score("Man United", "Man United") == 1.0
    assert name_score("Liverpool", "Brentford") < 0.5


def _db():
    conn = connect()
    conn.executemany(
        "INSERT INTO matches VALUES (?,?,?,?,?,?,?,?,0)",
        [("2026-05-24", "Liverpool", "Brentford", 2, 1, "EPL", "", ""),
         ("2026-05-24", "Man United", "Brighton", 0, 0, "EPL", "", ""),
         ("2026-05-24", "Villarreal", "Ath Madrid", 1, 1, "La Liga", "", "")])
    return conn


def test_resolve_event_orients_to_db_home_away():
    conn = _db()
    row, h, a = resolve_event(conn, "EPL", date(2026, 5, 24), "Brentford", "Liverpool")
    assert (row["home_team"], h, a) == ("Liverpool", "Liverpool", "Brentford")


def test_resolve_event_fuzzy_and_tournament_scoped():
    conn = _db()
    assert resolve_event(conn, "La Liga", date(2026, 5, 24), "Villarreal", "Atletico")
    assert resolve_event(conn, "EPL", date(2026, 5, 24), "Villarreal", "Atletico") is None


def test_club_series_use_world_cup_grammar():
    assert parse_contract("KXEPLGAME", "Tie", "Liverpool", "Brentford").name == "draw"
    assert parse_contract("KXEPLGAME", "Liverpool", "Liverpool", "Brentford").name == "home"
    assert parse_contract("KXEPLTOTAL", "Over 2.5 goals scored", "A", "B").line == 2.5
    assert parse_contract("KXEPLBTTS", "Both Teams To Score", "A", "B").name == "btts"
    assert parse_contract("KXEPLSPREAD", "Arsenal wins by over 1.5 goals", "Arsenal", "B").name == "home_spread"
    # non-soccer series must stay unmapped
    assert parse_contract("KXMLBGAME", "Yankees", "Yankees", "Red Sox") is None


def test_candle_price_handles_ohlc_dict_bid_ask():
    from kalshi_edge.backtest.replay import _candle_price
    c = {"price": {}, "yes_bid": {"close": "0.40"}, "yes_ask": {"close": "0.44"}}
    assert abs(_candle_price(c) - 0.42) < 1e-9


def test_alias_table_survives_normalisation():
    # football-data "FC Koln" normalises to "koln"; the alias key must too.
    assert name_score("1. FC Cologne", "FC Koln") >= 0.9
    assert name_score("Atletico", "Ath Madrid") >= 0.9
