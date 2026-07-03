from kalshi_edge.kalshi.models import OrderbookLevel, Orderbook, EffectivePrices, Fill


def _to_cents(price) -> int:
    """Accept int cents (60) or dollar string/float ('0.60', 0.6) -> int cents."""
    if isinstance(price, str):
        price = float(price)
    if isinstance(price, float):
        return round(price * 100) if price <= 1.0 else round(price)
    return int(price)


def _to_count(count) -> int:
    return int(float(count)) if isinstance(count, str) else int(count)


def _levels(rows) -> tuple[OrderbookLevel, ...]:
    if not rows:
        return ()
    levels = [OrderbookLevel(price=_to_cents(p), count=_to_count(c)) for p, c in rows]
    return tuple(sorted(levels, key=lambda lvl: lvl.price, reverse=True))


def parse_orderbook(raw: dict, ticker: str) -> Orderbook:
    yes_raw = raw.get("yes") or raw.get("yes_dollars")
    no_raw = raw.get("no") or raw.get("no_dollars")
    return Orderbook(ticker=ticker, yes=_levels(yes_raw), no=_levels(no_raw))
