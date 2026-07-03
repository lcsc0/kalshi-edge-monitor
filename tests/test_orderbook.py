from kalshi_edge.kalshi.models import OrderbookLevel, Orderbook, EffectivePrices, Fill


def test_models_construct():
    lvl = OrderbookLevel(price=60, count=100)
    ob = Orderbook(ticker="T", yes=(lvl,), no=())
    ep = EffectivePrices(yes_bid=0.60, yes_ask=None, yes_mid=None, spread=None)
    fill = Fill(filled=0, avg_price=None, slippage=None)
    assert lvl.price == 60 and ob.ticker == "T" and ep.yes_bid == 0.60 and fill.filled == 0
