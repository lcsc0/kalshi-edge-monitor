"""Reconstruct what the goal model would have priced at a pre-close time for a
historical settled Kalshi soccer market — **without lookahead**.

A backtest that lets the model peek at the match it is pricing always looks
brilliant and always lies. Two guards enforce this here (both tested):

1. The model's ``ref_date`` must be *strictly before* the match's kickoff date.
   ``strengths.decay_weight`` gives a zero-age match full weight, so a same-day
   ``ref_date`` would let the match's own result leak into the fit.
2. The pre-close price timestamp must be *strictly before* kickoff.

Anything else raises :class:`LookaheadError`.
"""
from dataclasses import dataclass
from datetime import date, datetime
import re

from kalshi_edge.model.goal_model import GoalModel
from kalshi_edge.model.strengths import DEFAULT_HALF_LIFE_DAYS
from kalshi_edge.pricer.pricer import Pricer


class LookaheadError(ValueError):
    """Raised when a replay would use data at or after the match it is pricing."""


@dataclass(frozen=True)
class ContractSpec:
    """A Pricer leg: ``name`` + optional ``line`` (see ``Pricer.price``).

    ``line`` is a float for totals/team-totals, an ``(h, a)`` tuple for exact
    score, or ``None`` for moneyline/BTTS.
    """
    name: str
    line: object = None


@dataclass(frozen=True)
class HistoricalMarket:
    ticker: str
    series: str
    home: str
    away: str
    kickoff: datetime          # tz-aware match start
    contract: ContractSpec | None  # None => market type we cannot map (unmapped)
    settled_yes: bool          # did the YES side settle in the money?
    neutral: bool = True


@dataclass(frozen=True)
class BacktestSignal:
    ticker: str
    kickoff: datetime
    model_fair: float          # model's fair YES probability at ref time
    market_price: float        # Kalshi YES price at the pre-close time (0..1)
    edge: float                # model_fair - market_price
    realized_outcome: int      # 1 if the YES side settled in the money else 0
    label: str = ""


# --------------------------------------------------------------------------- #
# Lookahead guard
# --------------------------------------------------------------------------- #

def assert_no_lookahead(ref_date: str, kickoff: datetime) -> None:
    """Require ``ref_date`` strictly before the kickoff calendar date."""
    ref = date.fromisoformat(ref_date[:10])
    if ref >= kickoff.date():
        raise LookaheadError(
            f"ref_date {ref} is not strictly before kickoff {kickoff.date()} — "
            "the match result could leak into the model fit")


# --------------------------------------------------------------------------- #
# Contract parsing (Kalshi series + subtitle -> Pricer leg)
# --------------------------------------------------------------------------- #

_OVER_RE = re.compile(r"over\s+(\d+(?:\.\d+)?)", re.I)
_UNDER_RE = re.compile(r"under\s+(\d+(?:\.\d+)?)", re.I)
_SCORE_RE = re.compile(r"(\d+)\s*-\s*(\d+)")


def _series_key(series: str) -> str:
    return (series or "").upper().split("-")[0]


def parse_contract(series: str, subtitle: str, home: str, away: str) -> ContractSpec | None:
    """Best-effort map of a Kalshi soccer market to a Pricer leg.

    Returns ``None`` for market types outside the SP2c Pricer surface
    (spreads, player goals, matchups) — the caller records them as *unmapped*.
    """
    key = _series_key(series)
    sub = (subtitle or "").strip()
    low = sub.lower()

    if key in ("KXWCGAME", "KXWCMATCHUP", "KXWCTEAMH2H"):
        # Moneyline: "Reg Time: <team>" / "Reg Time: Draw"
        target = re.sub(r"(?i)reg\s*time\s*:", "", sub).strip()
        if target.lower() in ("draw", "tie"):
            return ContractSpec("draw")
        if _norm(target) == _norm(home):
            return ContractSpec("home")
        if _norm(target) == _norm(away):
            return ContractSpec("away")
        return None

    if key in ("KXWCTOTAL", "KXWCTOTALGOAL"):
        m = _OVER_RE.search(low)
        if m:
            return ContractSpec("over", float(m.group(1)))
        m = _UNDER_RE.search(low)
        if m:
            return ContractSpec("under", float(m.group(1)))
        return None

    if key == "KXWCBTTS":
        if low.startswith("yes") or "both teams" in low:
            return ContractSpec("btts")
        if low.startswith("no"):
            return ContractSpec("btts_no")
        return None

    if key == "KXWCTEAMTOTAL":
        side = "home" if _norm(home) in _norm(sub) else ("away" if _norm(away) in _norm(sub) else None)
        if side is None:
            return None
        m = _OVER_RE.search(low)
        if m:
            return ContractSpec(f"{side}_over", float(m.group(1)))
        m = _UNDER_RE.search(low)
        if m:
            return ContractSpec(f"{side}_under", float(m.group(1)))
        return None

    if key == "KXWCSCORE":
        m = _SCORE_RE.search(sub)
        if m:
            return ContractSpec("exact", (int(m.group(1)), int(m.group(2))))
        return None

    # KXWCSPREAD, KXWCPLAYERGOALS, and anything unknown: not on the Pricer surface.
    return None


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


# --------------------------------------------------------------------------- #
# Candlestick price lookup (pre-close, no lookahead)
# --------------------------------------------------------------------------- #

def _norm_price(v) -> float:
    """Kalshi candlestick prices come as cents or dollar strings; -> probability."""
    v = float(v)
    return v / 100 if v > 1 else v


def _candle_price(c: dict) -> float | None:
    price = c.get("price")
    if isinstance(price, dict):
        for k in ("mean", "close", "previous", "open"):
            if price.get(k) not in (None, ""):
                return _norm_price(price[k])
    elif price not in (None, ""):
        return _norm_price(price)
    yb, ya = c.get("yes_bid"), c.get("yes_ask")
    if yb not in (None, "") and ya not in (None, ""):
        return (_norm_price(yb) + _norm_price(ya)) / 2
    for k in ("yes_price", "close", "mean"):
        if c.get(k) not in (None, ""):
            return _norm_price(c[k])
    return None


def price_at_or_before(candles: list[dict], ts: int) -> float | None:
    """Price from the last candle whose ``end_period_ts`` is <= ``ts``.

    Candles strictly after ``ts`` are ignored (that would be lookahead).
    Returns ``None`` if no candle precedes ``ts`` or none carries a price.
    """
    best = None
    for c in candles:
        t = c.get("end_period_ts")
        if t is None or t > ts:
            continue
        if best is None or t > best.get("end_period_ts"):
            best = c
    if best is None:
        return None
    return _candle_price(best)


# --------------------------------------------------------------------------- #
# Full replay
# --------------------------------------------------------------------------- #

def replay_market(conn, market: HistoricalMarket, *, ref_date: str, pre_close_ts: int,
                  candles: list[dict], since: str | None = None, rho: float = 0.0,
                  max_goals: int = 10,
                  half_life_days: float = DEFAULT_HALF_LIFE_DAYS) -> BacktestSignal | None:
    """Reconstruct one :class:`BacktestSignal`, or ``None`` if the market is
    unmapped or has no usable pre-close price.

    Guards against lookahead on both the model ``ref_date`` and the price
    timestamp before doing any work.
    """
    if market.contract is None:
        return None

    assert_no_lookahead(ref_date, market.kickoff)
    if pre_close_ts >= market.kickoff.timestamp():
        raise LookaheadError(
            f"pre_close_ts {pre_close_ts} is at/after kickoff "
            f"{int(market.kickoff.timestamp())}")

    market_price = price_at_or_before(candles, pre_close_ts)
    if market_price is None:
        return None

    model = GoalModel.from_db(conn, ref_date=ref_date, half_life_days=half_life_days,
                              since=since, rho=rho, max_goals=max_goals)
    pricer = Pricer.from_model(model, market.home, market.away, neutral=market.neutral)
    model_fair = pricer.price(market.contract.name, market.contract.line)

    return BacktestSignal(
        ticker=market.ticker,
        kickoff=market.kickoff,
        model_fair=model_fair,
        market_price=market_price,
        edge=model_fair - market_price,
        realized_outcome=1 if market.settled_yes else 0,
        label=f"{market.home} v {market.away} [{market.contract.name}]",
    )
