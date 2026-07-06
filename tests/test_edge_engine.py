from datetime import datetime, timedelta, timezone

from kalshi_edge.kalshi.models import Orderbook, OrderbookLevel
from kalshi_edge.edge.engine import EdgeEngine, EdgeSignal


def _book(ticker="MKT", yes_top=0.55, no_top=0.44, depth=500):
    """Book with yes-bid = yes_top and yes-ask = 1 - no_top, `depth` each side."""
    return Orderbook(
        ticker=ticker,
        yes=(OrderbookLevel(price=yes_top, count=depth),),
        no=(OrderbookLevel(price=no_top, count=depth),),
    )


ANALYSIS = {
    "home": "Strong", "away": "Weak", "neutral": True,
    "expected_goals": {"home": 2.1, "away": 0.7},
    "strength": {"Strong": {"attack": 1.4, "defense": 0.8},
                 "Weak": {"attack": 0.7, "defense": 1.3}},
    "outcome_probs": {"home": 0.72, "draw": 0.18, "away": 0.10},
}
NOW = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)


def _engine(**kw):
    return EdgeEngine(absurd_edge=0.15, max_slippage=0.02, max_age_seconds=900, **kw)


def test_healthy_market_emits_yes_signal_with_analysis():
    # yes_mid = (0.55 + 0.56)/2 = 0.555 ; model_fair 0.62 => edge +0.065 -> buy yes
    ob = _book(yes_top=0.55, no_top=0.44)
    sig = _engine().evaluate(
        ticker="MKT", model_fair=0.62, orderbook=ob, analysis=ANALYSIS,
        fetched_at=NOW - timedelta(seconds=60), intended_size=100, now=NOW)
    assert isinstance(sig, EdgeSignal)
    assert not sig.suppressed
    assert sig.side == "yes"
    assert abs(sig.market_implied - 0.555) < 1e-9
    assert abs(sig.edge - (0.62 - 0.555)) < 1e-9
    assert sig.fillable_size == 100
    assert sig.analysis["expected_goals"]["home"] == 2.1


def test_negative_edge_picks_no_side():
    ob = _book(yes_top=0.55, no_top=0.44)
    sig = _engine().evaluate(
        ticker="MKT", model_fair=0.50, orderbook=ob, analysis=ANALYSIS,
        fetched_at=NOW - timedelta(seconds=60), intended_size=100, now=NOW)
    assert sig.side == "no"
    assert sig.edge < 0


def test_absurd_edge_is_suppressed():
    ob = _book(yes_top=0.55, no_top=0.44)
    sig = _engine().evaluate(
        ticker="MKT", model_fair=0.95, orderbook=ob, analysis=ANALYSIS,
        fetched_at=NOW - timedelta(seconds=60), intended_size=100, now=NOW)
    assert sig.suppressed
    assert sig.suppression_reason == "absurd_edge"


def test_illiquid_market_is_suppressed():
    # only 10 contracts on the no-book, intended size 100 -> cannot fill
    ob = _book(yes_top=0.55, no_top=0.44, depth=10)
    sig = _engine().evaluate(
        ticker="MKT", model_fair=0.62, orderbook=ob, analysis=ANALYSIS,
        fetched_at=NOW - timedelta(seconds=60), intended_size=100, now=NOW)
    assert sig.suppressed
    assert sig.suppression_reason == "illiquid"


def test_high_slippage_is_suppressed():
    # deep enough to fill but the book is stacked so VWAP slips past the bound
    ob = Orderbook(
        ticker="MKT",
        yes=(OrderbookLevel(price=0.55, count=500),),
        no=(OrderbookLevel(price=0.44, count=5),
            OrderbookLevel(price=0.20, count=500)),  # deep but far worse ask
    )
    sig = _engine().evaluate(
        ticker="MKT", model_fair=0.62, orderbook=ob, analysis=ANALYSIS,
        fetched_at=NOW - timedelta(seconds=60), intended_size=100, now=NOW)
    assert sig.suppressed
    assert sig.suppression_reason == "illiquid"


def test_stale_data_is_suppressed():
    ob = _book(yes_top=0.55, no_top=0.44)
    sig = _engine().evaluate(
        ticker="MKT", model_fair=0.62, orderbook=ob, analysis=ANALYSIS,
        fetched_at=NOW - timedelta(seconds=1800), intended_size=100, now=NOW)
    assert sig.suppressed
    assert sig.suppression_reason == "stale"


def test_market_prices_partition_devigged_for_implied():
    # full moneyline partition sums to 1.20; home devigged = 0.50/1.20 = 0.41667
    ob = _book(yes_top=0.40, no_top=0.58)
    sig = _engine().evaluate(
        ticker="HOME", model_fair=0.45, orderbook=ob, analysis=ANALYSIS,
        fetched_at=NOW - timedelta(seconds=60), intended_size=50, now=NOW,
        market_prices={"home": 0.50, "draw": 0.30, "away": 0.40},
        contract_key="home")
    assert abs(sig.market_implied - 0.50 / 1.20) < 1e-9
