"""Offline test of the live wiring: fake Kalshi client + in-memory model ->
build_games -> build_report. Exercises matchup inference, team resolution,
contract mapping, unmapped/unknown-team skipping, and the full render."""
from datetime import datetime, timezone

from kalshi_edge.data.cache import connect
from kalshi_edge.data.intl_results import load_results_csv
from kalshi_edge.model.goal_model import GoalModel
from kalshi_edge.kalshi.models import Orderbook, OrderbookLevel
from kalshi_edge.edge.engine import EdgeEngine

import importlib.util
import pathlib

# recommend.py lives in scripts/ (on the pytest pythonpath) — import as a module.
_spec = importlib.util.spec_from_file_location(
    "recommend", pathlib.Path(__file__).resolve().parents[1] / "scripts" / "recommend.py")
recommend = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(recommend)

NOW = datetime(2025, 10, 1, 12, 0, tzinfo=timezone.utc)
GAME_TIME = "2025-10-01T18:00:00Z"

ROWS = "date,home_team,away_team,home_score,away_score,tournament,city,country,neutral\n" + "".join(
    f"2025-0{i%9+1}-01,Strong,Weak,3,0,Friendly,X,Y,TRUE\n"
    f"2025-0{i%9+1}-15,Weak,Strong,0,3,Friendly,X,Y,TRUE\n" for i in range(10))


def _model():
    conn = connect(); load_results_csv(conn, ROWS)
    return GoalModel.from_db(conn, ref_date="2025-10-01")


def _ob():
    return Orderbook(ticker="X",
                     yes=(OrderbookLevel(price=0.40, count=500),),
                     no=(OrderbookLevel(price=0.55, count=500),))


class FakeClient:
    def __init__(self, markets):
        self._markets = markets

    def iter_markets(self, *, status="open", series_ticker=None, **_):
        for m in self._markets:
            if series_ticker is None or m.get("series_ticker") == series_ticker:
                yield m

    def get_orderbook(self, ticker):
        return _ob()


def _market(ticker, series, sub, event="EVT-STRONG-WEAK"):
    return {"ticker": ticker, "series_ticker": series, "yes_sub_title": sub,
            "event_ticker": event, "occurrence_datetime": GAME_TIME}


def test_build_games_maps_event_and_skips_unmapped():
    markets = [
        _market("M-HOME", "KXWCGAME", "Reg Time: Strong"),
        _market("M-DRAW", "KXWCGAME", "Reg Time: Draw"),
        _market("M-AWAY", "KXWCGAME", "Reg Time: Weak"),
        _market("M-OVER", "KXWCTOTAL", "Over 2.5 goals scored"),
        _market("M-SPREAD", "KXWCSPREAD", "Strong wins by more than 1.5 goals"),
        _market("M-PLAYER", "KXWCPLAYERGOALS", "Some Striker: 1+"),
    ]
    client = FakeClient(markets)
    games, skipped = recommend.build_games(
        client, _model(), series_tickers=["KXWCGAME", "KXWCTOTAL", "KXWCSPREAD", "KXWCPLAYERGOALS"],
        target=NOW.date(), now=NOW)

    assert len(games) == 1
    g = games[0]
    assert g["home"] == "Strong" and g["away"] == "Weak"
    contracts = {m["contract"] for m in g["markets"]}
    assert contracts == {"home", "draw", "away", "over", "home_spread"}  # player prop dropped
    assert any("M-PLAYER" in s and "unmapped" in s for s in skipped)


def test_build_games_skips_unknown_team():
    markets = [
        _market("U-HOME", "KXWCGAME", "Reg Time: Atlantis", event="EVT-U"),
        _market("U-AWAY", "KXWCGAME", "Reg Time: Weak", event="EVT-U"),
    ]
    games, skipped = recommend.build_games(
        FakeClient(markets), _model(), series_tickers=["KXWCGAME"],
        target=NOW.date(), now=NOW)
    assert games == []
    assert any("Atlantis" in s for s in skipped)


def test_build_report_renders_from_built_games():
    markets = [
        _market("M-HOME", "KXWCGAME", "Reg Time: Strong"),
        _market("M-AWAY", "KXWCGAME", "Reg Time: Weak"),
        _market("M-OVER", "KXWCTOTAL", "Over 2.5 goals scored"),
    ]
    games, _ = recommend.build_games(
        FakeClient(markets), _model(), series_tickers=["KXWCGAME", "KXWCTOTAL"],
        target=NOW.date(), now=NOW)
    report = recommend.build_report(games, engine=EdgeEngine(), now=NOW,
                                    bankroll=1000.0, date="2025-10-01")
    assert "UNVALIDATED MODEL" in report
    assert "Strong" in report and "Weak" in report
