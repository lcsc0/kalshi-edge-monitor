from datetime import date
from kalshi_edge.kalshi.soccer import filter_markets_on_game_date, market_game_date


def test_market_game_date_uses_occurrence_not_close_time():
    m = {"occurrence_datetime": "2026-07-03T21:00:00Z", "close_time": "2026-07-17T18:00:00Z"}
    assert market_game_date(m) == date(2026, 7, 3)


def test_market_game_date_falls_back_to_expected_expiration():
    m = {"expected_expiration_time": "2026-07-03T23:00:00Z", "close_time": "2026-07-17T18:00:00Z"}
    assert market_game_date(m) == date(2026, 7, 3)


def test_market_game_date_none_when_missing():
    assert market_game_date({"close_time": "2026-07-17T18:00:00Z"}) is None


def test_filter_keeps_only_markets_whose_game_is_on_target_date():
    markets = [
        {"ticker": "A", "occurrence_datetime": "2026-07-03T21:00:00Z",
         "close_time": "2026-07-17T18:00:00Z"},
        {"ticker": "B", "occurrence_datetime": "2026-07-04T18:00:00Z"},
        {"ticker": "C", "expected_expiration_time": "2026-07-03T23:00:00Z"},
    ]
    kept = [m["ticker"] for m in filter_markets_on_game_date(markets, date(2026, 7, 3))]
    assert kept == ["A", "C"]
