from kalshi_edge.kalshi.models import OrderbookLevel, Orderbook, EffectivePrices, Fill
from kalshi_edge.kalshi.orderbook import parse_orderbook, effective_prices, simulate_buy_yes, simulate_buy_no


def test_models_construct():
    lvl = OrderbookLevel(price=0.60, count=100)
    ob = Orderbook(ticker="T", yes=(lvl,), no=())
    ep = EffectivePrices(yes_bid=0.60, yes_ask=None, yes_mid=None, spread=None)
    fill = Fill(filled=0, avg_price=None, slippage=None)
    assert lvl.price == 0.60 and ob.ticker == "T" and ep.yes_bid == 0.60 and fill.filled == 0


def test_parse_int_cents_normalize_to_probability_and_sort_best_first():
    raw = {"yes": [[59, 50], [60, 100]], "no": [[37, 100], [38, 200]]}
    ob = parse_orderbook(raw, ticker="T")
    assert ob.yes[0].price == 0.60 and ob.yes[0].count == 100
    assert ob.yes[1].price == 0.59
    assert ob.no[0].price == 0.38 and ob.no[0].count == 200


def test_parse_dollar_string_shape_is_probability():
    raw = {"yes_dollars": [["0.60", "100"]], "no_dollars": [["0.38", "200"]]}
    ob = parse_orderbook(raw, ticker="T")
    assert ob.yes[0].price == 0.60 and ob.yes[0].count == 100
    assert ob.no[0].price == 0.38 and ob.no[0].count == 200


def test_parse_real_orderbook_fp_subcent_dollars():
    # Shape observed live: dollar strings incl. sub-cent, fixed-point counts.
    raw = {"yes_dollars": [["0.0010", "5000.00"]], "no_dollars": [["0.62", "10.00"]]}
    ob = parse_orderbook(raw, ticker="T")
    assert ob.yes[0].price == 0.001 and ob.yes[0].count == 5000
    assert ob.no[0].price == 0.62
    ep = effective_prices(ob)
    assert ep.yes_bid == 0.001
    assert round(ep.yes_ask, 4) == 0.38  # 1 - 0.62


def test_parse_empty_sides():
    ob = parse_orderbook({"yes": None, "no": []}, ticker="T")
    assert ob.yes == () and ob.no == ()


def test_effective_prices_reconstructs_ask_from_no_bid():
    raw = {"yes": [[60, 100], [59, 50]], "no": [[38, 200], [37, 100]]}
    ep = effective_prices(parse_orderbook(raw, "T"))
    assert ep.yes_bid == 0.60
    assert round(ep.yes_ask, 4) == 0.62
    assert round(ep.yes_mid, 4) == 0.61
    assert round(ep.spread, 4) == 0.02


def test_effective_prices_handles_one_sided_book():
    ep_no_asks = effective_prices(parse_orderbook({"yes": [[60, 100]], "no": []}, "T"))
    assert ep_no_asks.yes_bid == 0.60 and ep_no_asks.yes_ask is None
    assert ep_no_asks.yes_mid is None and ep_no_asks.spread is None


def test_buy_yes_walks_no_book_and_computes_vwap_slippage():
    raw = {"yes": [[60, 100]], "no": [[38, 200], [37, 150]]}
    fill = simulate_buy_yes(parse_orderbook(raw, "T"), size=250)
    assert fill.filled == 250
    assert round(fill.avg_price, 4) == 0.622
    assert round(fill.slippage, 4) == 0.002


def test_buy_yes_partial_when_book_too_thin():
    fill = simulate_buy_yes(parse_orderbook({"yes": [], "no": [[38, 100]]}, "T"), size=250)
    assert fill.filled == 100 and round(fill.avg_price, 4) == 0.62


def test_buy_yes_empty_book_returns_no_fill():
    fill = simulate_buy_yes(parse_orderbook({"yes": [], "no": []}, "T"), size=10)
    assert fill == Fill(filled=0, avg_price=None, slippage=None)


def test_buy_no_walks_yes_book():
    raw = {"yes": [[60, 100], [59, 100]], "no": [[38, 200]]}
    fill = simulate_buy_no(parse_orderbook(raw, "T"), size=150)
    assert fill.filled == 150 and round(fill.avg_price, 5) == 0.40333
