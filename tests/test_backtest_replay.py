from datetime import datetime, timezone

import pytest

from kalshi_edge.data.cache import connect
from kalshi_edge.data.intl_results import load_results_csv
from kalshi_edge.backtest.replay import (
    LookaheadError,
    ContractSpec,
    HistoricalMarket,
    BacktestSignal,
    assert_no_lookahead,
    parse_contract,
    price_at_or_before,
    replay_market,
)

# A synthetic results table: "Strong" thrashes "Weak" repeatedly, on neutral ground,
# all well before any backtested kickoff, so the model can be fit without lookahead.
ROWS = "date,home_team,away_team,home_score,away_score,tournament,city,country,neutral\n" + "".join(
    f"2024-0{i%9+1}-01,Strong,Weak,3,0,Friendly,X,Y,TRUE\n"
    f"2024-0{i%9+1}-15,Weak,Strong,0,3,Friendly,X,Y,TRUE\n" for i in range(10))

KICKOFF = datetime(2025, 6, 1, 18, 0, tzinfo=timezone.utc)


def _db():
    conn = connect()
    load_results_csv(conn, ROWS)
    return conn


# ---- leakage guard ----

def test_assert_no_lookahead_allows_ref_before_kickoff():
    assert_no_lookahead("2025-05-31", KICKOFF)  # does not raise


def test_assert_no_lookahead_rejects_same_day_ref():
    with pytest.raises(LookaheadError):
        assert_no_lookahead("2025-06-01", KICKOFF)


def test_assert_no_lookahead_rejects_future_ref():
    with pytest.raises(LookaheadError):
        assert_no_lookahead("2025-06-02", KICKOFF)


# ---- contract parser ----

def test_parse_moneyline_home_away_draw():
    assert parse_contract("KXWCGAME", "Reg Time: Strong", "Strong", "Weak").name == "home"
    assert parse_contract("KXWCGAME", "Reg Time: Weak", "Strong", "Weak").name == "away"
    assert parse_contract("KXWCGAME", "Reg Time: Draw", "Strong", "Weak").name == "draw"


def test_parse_totals():
    over = parse_contract("KXWCTOTAL", "Over 1.5 goals scored", "Strong", "Weak")
    assert over.name == "over" and over.line == 1.5
    under = parse_contract("KXWCTOTAL", "Under 2.5 goals", "Strong", "Weak")
    assert under.name == "under" and under.line == 2.5


def test_parse_btts():
    assert parse_contract("KXWCBTTS", "Yes", "Strong", "Weak").name == "btts"
    assert parse_contract("KXWCBTTS", "No", "Strong", "Weak").name == "btts_no"


def test_parse_team_total():
    spec = parse_contract("KXWCTEAMTOTAL", "Strong Over 1.5 goals", "Strong", "Weak")
    assert spec.name == "home_over" and spec.line == 1.5
    spec2 = parse_contract("KXWCTEAMTOTAL", "Weak Under 0.5 goals", "Strong", "Weak")
    assert spec2.name == "away_under" and spec2.line == 0.5


def test_parse_correct_score():
    spec = parse_contract("KXWCSCORE", "2-1", "Strong", "Weak")
    assert spec.name == "exact" and spec.line == (2, 1)


def test_parse_spread_maps_to_margin_leg():
    spec = parse_contract("KXWCSPREAD", "Strong wins by more than 1.5 goals", "Strong", "Weak")
    assert spec.name == "home_spread" and spec.line == 1.5


def test_parse_unmapped_types_return_none():
    # Player props aren't a joint-matrix contract — priced separately.
    assert parse_contract("KXWCPLAYERGOALS", "Lionel Messi: 1+", "Strong", "Weak") is None


# ---- candlestick price lookup ----

def test_price_at_or_before_picks_last_preceding_and_normalizes_cents():
    candles = [
        {"end_period_ts": 100, "price": {"mean": 40}},
        {"end_period_ts": 200, "price": {"mean": 55}},
        {"end_period_ts": 300, "price": {"mean": 80}},  # after our cutoff -> ignored
    ]
    assert price_at_or_before(candles, 250) == pytest.approx(0.55)


def test_price_at_or_before_none_when_nothing_precedes():
    candles = [{"end_period_ts": 500, "price": {"mean": 55}}]
    assert price_at_or_before(candles, 100) is None


def test_price_at_or_before_supports_bid_ask_mid():
    candles = [{"end_period_ts": 100, "yes_bid": 50, "yes_ask": 60}]
    assert price_at_or_before(candles, 150) == pytest.approx(0.55)


# ---- full replay ----

def _market(contract):
    return HistoricalMarket(
        ticker="KXWCGAME-25JUN01STRWEA-STR",
        series="KXWCGAME",
        home="Strong",
        away="Weak",
        kickoff=KICKOFF,
        contract=contract,
        settled_yes=True,
        neutral=True,
    )


def test_replay_market_builds_signal_without_lookahead():
    conn = _db()
    pre_close_ts = int(datetime(2025, 6, 1, 16, 0, tzinfo=timezone.utc).timestamp())
    candles = [{"end_period_ts": pre_close_ts - 60, "price": {"mean": 60}}]
    sig = replay_market(conn, _market(ContractSpec("home")), ref_date="2025-05-31",
                        pre_close_ts=pre_close_ts, candles=candles, since="2023-01-01")
    assert isinstance(sig, BacktestSignal)
    assert sig.market_price == pytest.approx(0.60)
    assert sig.model_fair > 0.6  # Strong is a heavy favorite
    assert sig.edge == pytest.approx(sig.model_fair - sig.market_price)
    assert sig.realized_outcome == 1  # settled_yes


def test_replay_unmapped_market_returns_none():
    conn = _db()
    m = _market(None)
    ts = int(datetime(2025, 6, 1, 16, 0, tzinfo=timezone.utc).timestamp())
    assert replay_market(conn, m, ref_date="2025-05-31", pre_close_ts=ts, candles=[]) is None


def test_replay_raises_on_lookahead_ref_date():
    conn = _db()
    ts = int(datetime(2025, 6, 1, 16, 0, tzinfo=timezone.utc).timestamp())
    candles = [{"end_period_ts": ts - 60, "price": {"mean": 60}}]
    with pytest.raises(LookaheadError):
        # ref_date on kickoff day -> the match result could leak into the fit
        replay_market(conn, _market(ContractSpec("home")), ref_date="2025-06-01",
                      pre_close_ts=ts, candles=candles)


def test_replay_raises_when_price_timestamp_after_kickoff():
    conn = _db()
    after = int(datetime(2025, 6, 1, 20, 0, tzinfo=timezone.utc).timestamp())  # post-kickoff
    candles = [{"end_period_ts": after - 60, "price": {"mean": 60}}]
    with pytest.raises(LookaheadError):
        replay_market(conn, _market(ContractSpec("home")), ref_date="2025-05-31",
                      pre_close_ts=after, candles=candles)
