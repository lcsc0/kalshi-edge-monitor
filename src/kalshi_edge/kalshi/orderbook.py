from kalshi_edge.kalshi.models import OrderbookLevel, Orderbook, EffectivePrices, Fill


def _to_price(price) -> float:
    """Normalize a raw price to dollars, which equals probability (0..1).

    Kalshi's live `orderbook_fp` returns dollar strings ('0.60', sub-cent '0.0010').
    Some inputs use whole cents (60). Heuristic: a value > 1 is cents -> divide by 100.
    A Kalshi dollar price already equals the contract's implied probability.
    """
    if isinstance(price, str):
        price = float(price)
    return price / 100 if price > 1 else float(price)


def _to_count(count) -> int:
    return int(float(count)) if isinstance(count, str) else int(count)


def _levels(rows) -> tuple[OrderbookLevel, ...]:
    if not rows:
        return ()
    levels = [OrderbookLevel(price=_to_price(p), count=_to_count(c)) for p, c in rows]
    return tuple(sorted(levels, key=lambda lvl: lvl.price, reverse=True))


def parse_orderbook(raw: dict, ticker: str) -> Orderbook:
    yes_raw = raw.get("yes") or raw.get("yes_dollars")
    no_raw = raw.get("no") or raw.get("no_dollars")
    return Orderbook(ticker=ticker, yes=_levels(yes_raw), no=_levels(no_raw))


def effective_prices(ob: Orderbook) -> EffectivePrices:
    yes_bid = ob.yes[0].price if ob.yes else None
    yes_ask = (1 - ob.no[0].price) if ob.no else None
    if yes_bid is not None and yes_ask is not None:
        mid = (yes_bid + yes_ask) / 2
        spread = yes_ask - yes_bid
    else:
        mid = spread = None
    return EffectivePrices(yes_bid=yes_bid, yes_ask=yes_ask, yes_mid=mid, spread=spread)


def _simulate(levels: tuple[OrderbookLevel, ...], size: int) -> Fill:
    """Walk `levels` (already best-first), where each level offers the opposite
    side at (1 - level.price) dollars. Returns VWAP fill and slippage vs top,
    both as probabilities (dollars)."""
    remaining, cost, filled, best = size, 0.0, 0, None
    for lvl in levels:
        ask = 1 - lvl.price
        if best is None:
            best = ask
        take = min(remaining, lvl.count)
        cost += take * ask
        filled += take
        remaining -= take
        if remaining == 0:
            break
    if filled == 0:
        return Fill(filled=0, avg_price=None, slippage=None)
    avg = cost / filled
    return Fill(filled=filled, avg_price=avg, slippage=avg - best)


def simulate_buy_yes(ob: Orderbook, size: int) -> Fill:
    return _simulate(ob.no, size)   # buying YES consumes the NO-bid book


def simulate_buy_no(ob: Orderbook, size: int) -> Fill:
    return _simulate(ob.yes, size)  # buying NO consumes the YES-bid book
