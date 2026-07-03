from kalshi_edge.kalshi.models import OrderbookLevel, Orderbook, EffectivePrices, Fill
from kalshi_edge.kalshi.orderbook import parse_orderbook, effective_prices


def test_models_construct():
    lvl = OrderbookLevel(price=60, count=100)
    ob = Orderbook(ticker="T", yes=(lvl,), no=())
    ep = EffectivePrices(yes_bid=0.60, yes_ask=None, yes_mid=None, spread=None)
    fill = Fill(filled=0, avg_price=None, slippage=None)
    assert lvl.price == 60 and ob.ticker == "T" and ep.yes_bid == 0.60 and fill.filled == 0


def test_parse_cents_int_shape_sorts_best_first():
    raw = {"yes": [[59, 50], [60, 100]], "no": [[37, 100], [38, 200]]}
    ob = parse_orderbook(raw, ticker="T")
    assert ob.yes[0].price == 60 and ob.yes[0].count == 100
    assert ob.yes[1].price == 59
    assert ob.no[0].price == 38 and ob.no[0].count == 200


def test_parse_dollar_string_shape_normalizes_to_cents():
    raw = {"yes_dollars": [["0.60", "100"]], "no_dollars": [["0.38", "200"]]}
    ob = parse_orderbook(raw, ticker="T")
    assert ob.yes[0].price == 60 and ob.yes[0].count == 100
    assert ob.no[0].price == 38 and ob.no[0].count == 200


def test_parse_empty_sides():
    ob = parse_orderbook({"yes": None, "no": []}, ticker="T")
    assert ob.yes == () and ob.no == ()


def test_effective_prices_reconstructs_ask_from_no_bid():
    raw = {"yes": [[60, 100], [59, 50]], "no": [[38, 200], [37, 100]]}
    ep = effective_prices(parse_orderbook(raw, "T"))
    assert ep.yes_bid == 0.60
    assert ep.yes_ask == 0.62
    assert ep.yes_mid == 0.61
    assert round(ep.spread, 4) == 0.02


def test_effective_prices_handles_one_sided_book():
    ep_no_asks = effective_prices(parse_orderbook({"yes": [[60, 100]], "no": []}, "T"))
    assert ep_no_asks.yes_bid == 0.60 and ep_no_asks.yes_ask is None
    assert ep_no_asks.yes_mid is None and ep_no_asks.spread is None
