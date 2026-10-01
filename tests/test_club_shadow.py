from datetime import datetime, timedelta, timezone

from kalshi_edge.data.cache import connect
from kalshi_edge.data.club_results import load_fixtures_csv
from kalshi_edge.edge.club_shadow import build_club_signals
from kalshi_edge.edge.engine import EdgeEngine
from kalshi_edge.kalshi.models import Orderbook, OrderbookLevel as L
from kalshi_edge.model.mle import DCFit
from kalshi_edge.model.mle_model import MLEGoalModel

NOW = datetime(2026, 10, 10, 9, 0, tzinfo=timezone.utc)


def _fixtures(kick="15:00", day="11/10/2026"):
    return ("Div,Date,Time,HomeTeam,AwayTeam\n"
            f"E0,{day},{kick},Liverpool,Brentford\n")


def _model():
    fit = DCFit(attack={"Liverpool": 0.3, "Brentford": 0.0}, defense={"Liverpool": 0.2, "Brentford": 0.0},
                home_adv=0.25, rho=-0.05)
    return MLEGoalModel(fit)


class FakeClient:
    def __init__(self, markets):
        self.markets = markets

    def iter_markets(self, *, series_ticker, status="open", **kw):
        return iter([m for m in self.markets if m["ticker"].startswith(series_ticker + "-")])

    def get_orderbook(self, ticker):
        return Orderbook(ticker=ticker, yes=(L(0.40, 500),), no=(L(0.55, 500),))


def _mk(series, suffix, tail, sub):
    return {"ticker": f"{series}-{suffix}-{tail}", "event_ticker": f"{series}-{suffix}", "yes_sub_title": sub}


MARKETS = [
    _mk("KXEPLGAME", "26OCT11LFCBRE", "LFC", "Liverpool"),
    _mk("KXEPLGAME", "26OCT11LFCBRE", "BRE", "Brentford"),
    _mk("KXEPLGAME", "26OCT11LFCBRE", "TIE", "Tie"),
    _mk("KXEPLTOTAL", "26OCT11LFCBRE", "2", "Over 2.5 goals scored"),
    _mk("KXEPLBTTS", "26OCT11LFCBRE", "BTTS", "Both Teams To Score"),
]


def _run(fixtures, markets=MARKETS, now=NOW, **kw):
    fix = connect()
    load_fixtures_csv(fix, fixtures)
    return build_club_signals(FakeClient(markets), _model(), fix, EdgeEngine(), now=now,
                              leagues=["EPL"], **kw)


def test_prices_all_legs_and_keeps_raw_model_probability():
    signals, stats = _run(_fixtures())
    assert stats["priced"] == 5
    by = {s.ticker: s for s in signals}
    assert by["KXEPLGAME-26OCT11LFCBRE-LFC"].raw_model_fair > by["KXEPLGAME-26OCT11LFCBRE-BRE"].raw_model_fair
    assert all(s.entry_price is None or 0 < s.entry_price < 1 for s in signals)


def test_fixture_orientation_decides_home_and_away():
    # Kalshi lists Brentford first; the fixture says Liverpool is at home. Liverpool
    # (stronger, at home) must be the favourite regardless of Kalshi ordering.
    flipped = list(reversed(MARKETS[:2])) + MARKETS[2:]
    signals, _ = _run(_fixtures(), markets=flipped)
    by = {s.ticker: s for s in signals}
    assert by["KXEPLGAME-26OCT11LFCBRE-LFC"].raw_model_fair > 0.4


def test_skips_markets_already_in_play_or_started():
    kickoff_utc_14 = NOW.replace(hour=14)  # 15:00 BST == 14:00 UTC
    signals, stats = _run(_fixtures(day="10/10/2026"), now=kickoff_utc_14 + timedelta(minutes=10))
    assert signals == [] and stats["in_play_or_started"] == 1


def test_skips_when_kickoff_unknown_or_beyond_horizon():
    assert _run(_fixtures(kick=""))[1].get("no_kickoff") == 1
    assert _run(_fixtures(day="11/10/2026"), horizon_days=0)[1].get("beyond_horizon") == 1


def test_skips_unknown_team_instead_of_guessing():
    fix = connect()
    load_fixtures_csv(fix, "Div,Date,Time,HomeTeam,AwayTeam\nE0,11/10/2026,15:00,Liverpool,Brentford\n")
    model = MLEGoalModel(DCFit(attack={"Liverpool": 0.3}, defense={"Liverpool": 0.2}, home_adv=0.2, rho=0.0))
    signals, stats = build_club_signals(FakeClient(MARKETS), model, fix, EdgeEngine(), now=NOW, leagues=["EPL"])
    assert signals == [] and stats["unknown_team"] == 1
