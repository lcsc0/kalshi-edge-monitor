import random
import sqlite3

from kalshi_edge.data.cache import connect
from kalshi_edge.edge.blend import BlendTable, fit_blend
from kalshi_edge.edge.engine import EdgeEngine, EdgeSignal
from kalshi_edge.edge.settle import (
    fee_per_contract, paper_pnl, render_scorecard, scorecard, settle_signals)
from kalshi_edge.edge.signal_log import ensure_table, log_signal
from kalshi_edge.kalshi.models import Orderbook, OrderbookLevel as L


def _sig(ticker, side="yes", raw=0.60, fair=0.60, market=0.50, entry=0.52, suppressed=False):
    return EdgeSignal(ticker=ticker, side=side, model_fair=fair, market_implied=market,
                      edge=fair - market, fillable_size=100, slippage=0.0,
                      suppressed=suppressed, suppression_reason=None, analysis={},
                      raw_model_fair=raw, entry_price=entry)


def test_ensure_table_migrates_old_schema():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE signal_log (id INTEGER PRIMARY KEY, ticker TEXT, side TEXT, "
                 "model_fair REAL, market_implied REAL, edge REAL, fillable_size INTEGER, "
                 "slippage REAL, suppressed INTEGER, suppression_reason TEXT, analysis TEXT, "
                 "fetched_at TEXT, logged_at TEXT, outcome INTEGER)")
    ensure_table(conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(signal_log)")}
    assert {"raw_model_fair", "entry_price", "result_yes", "settled_at"} <= cols
    ensure_table(conn)  # idempotent


def test_settle_sets_truth_and_side_outcome():
    conn = connect(); ensure_table(conn)
    log_signal(conn, _sig("KXEPLGAME-A-X", side="yes"), "t")
    log_signal(conn, _sig("KXEPLGAME-B-Y", side="no"), "t")
    log_signal(conn, _sig("KXEPLGAME-C-Z"), "t")
    res = {"KXEPLGAME-A-X": True, "KXEPLGAME-B-Y": True, "KXEPLGAME-C-Z": None}
    stats = settle_signals(conn, res.get)
    assert stats == {"tickers": 3, "settled": 2, "pending": 1}
    rows = {r["ticker"]: r for r in conn.execute("SELECT * FROM signal_log")}
    assert rows["KXEPLGAME-A-X"]["result_yes"] == 1 and rows["KXEPLGAME-A-X"]["outcome"] == 1
    assert rows["KXEPLGAME-B-Y"]["result_yes"] == 1 and rows["KXEPLGAME-B-Y"]["outcome"] == 0
    assert rows["KXEPLGAME-C-Z"]["result_yes"] is None
    # already-settled tickers are not re-fetched; only the pending one is re-checked
    asked = []
    settle_signals(conn, lambda t: asked.append(t))
    assert asked == ["KXEPLGAME-C-Z"]


def test_paper_pnl_net_of_fee_and_only_for_bets():
    win = {"suppressed": 0, "entry_price": 0.40, "outcome": 1}
    loss = {"suppressed": 0, "entry_price": 0.40, "outcome": 0}
    assert abs(paper_pnl(win) - (0.60 - fee_per_contract(0.40))) < 1e-12
    assert abs(paper_pnl(loss) - (-0.40 - fee_per_contract(0.40))) < 1e-12
    assert paper_pnl({**win, "suppressed": 1}) is None


def test_scorecard_dedupes_repeat_logs_and_compares_to_market():
    conn = connect(); ensure_table(conn)
    for _ in range(5):  # monitor re-ran 5x on the same market: counts once
        log_signal(conn, _sig("KXEPLGAME-A-X", raw=0.9, market=0.5), "t")
    log_signal(conn, _sig("KXEPLGAME-B-Y", raw=0.2, market=0.5, side="no"), "t")
    settle_signals(conn, {"KXEPLGAME-A-X": True, "KXEPLGAME-B-Y": False}.get)
    (row,) = scorecard(conn)
    assert row["series"] == "KXEPLGAME" and row["n"] == 2
    assert row["brier_model"] < row["brier_market"]  # model was right both times
    assert "model" in render_scorecard([row])


def _samples(n, edge_real, seed=0):
    """market p ~ U(.2,.8); truth drawn from p + edge_real*(model - p)."""
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        market = rng.uniform(0.2, 0.8)
        model = min(0.97, max(0.03, market + rng.uniform(-0.1, 0.1)))
        true_p = market + edge_real * (model - market)
        out.append((model, market, 1 if rng.random() < true_p else 0))
    return out


def test_blend_weight_zero_when_model_is_noise():
    assert fit_blend(_samples(4000, 0.0), min_n=300).weight == 0.0


def test_blend_weight_positive_when_model_has_signal():
    f = fit_blend(_samples(6000, 1.0), min_n=300)
    assert 0.3 < f.weight <= min(1.0, f.w_hat)


def test_blend_weight_zero_below_min_n_even_if_great():
    assert fit_blend(_samples(100, 1.0), min_n=300).weight == 0.0


def test_blend_table_collapses_to_market_by_default():
    t = BlendTable()
    assert t("KXANY", 0.9, 0.5) == 0.5


def test_engine_blend_zero_weight_means_no_edge_and_keeps_raw():
    eng = EdgeEngine()
    ob = Orderbook(ticker="KXEPLGAME-A-X", yes=(L(0.49, 500),), no=(L(0.49, 500),))
    sig = eng.evaluate("KXEPLGAME-A-X", 0.70, ob, {}, fetched_at=__import__("datetime").datetime.now(
        __import__("datetime").timezone.utc), intended_size=10, blend=BlendTable())
    assert abs(sig.edge) < 1e-9 and sig.raw_model_fair == 0.70
    assert sig.entry_price is not None
