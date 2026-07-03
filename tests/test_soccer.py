from datetime import date
from kalshi_edge.kalshi.soccer import filter_markets_closing_on


def test_filter_keeps_only_markets_closing_on_target_date():
    markets = [
        {"ticker": "A", "close_time": "2026-07-03T18:00:00Z"},
        {"ticker": "B", "close_time": "2026-07-04T18:00:00Z"},
        {"ticker": "C", "close_time": "2026-07-03T23:59:00Z"},
    ]
    kept = [m["ticker"] for m in filter_markets_closing_on(markets, date(2026, 7, 3))]
    assert kept == ["A", "C"]
