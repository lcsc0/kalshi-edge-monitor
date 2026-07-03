from dataclasses import dataclass


@dataclass(frozen=True)
class OrderbookLevel:
    price: int   # cents, 1..99
    count: int   # number of contracts resting at this price


@dataclass(frozen=True)
class Orderbook:
    ticker: str
    yes: tuple[OrderbookLevel, ...]  # resting YES bids, best (highest price) first
    no: tuple[OrderbookLevel, ...]   # resting NO bids, best (highest price) first


@dataclass(frozen=True)
class EffectivePrices:
    yes_bid: float | None   # probability 0..1
    yes_ask: float | None
    yes_mid: float | None
    spread: float | None


@dataclass(frozen=True)
class Fill:
    filled: int             # contracts actually fillable
    avg_price: float | None # VWAP as probability 0..1
    slippage: float | None  # avg_price - best-of-book price
