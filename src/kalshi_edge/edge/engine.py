"""Edge engine: model fair prob vs Kalshi de-vigged price, with §3 guardrails.

For a live market the engine computes the model's fair probability (from the
`Pricer`), the market's de-vigged implied probability (from the order book, or
by de-vigging the full contract partition when it is supplied), and the edge
``model_fair - market_implied``. It then applies the design §3 guardrails in
order and emits a structured :class:`EdgeSignal`:

1. **Staleness gate** — refuse if the underlying data is older than ``max_age_seconds``.
2. **Absurd-edge suppression** — if ``abs(edge) > absurd_edge`` treat it as a
   probable model/data error and suppress (do not recommend).
3. **Liquidity gate** — only surface a signal if the order book can fill the
   intended size within ``max_slippage`` (via ``simulate_buy_yes/no``).

The signal always carries the model's ``analysis`` record so the report can show
*why* (design §3a), never a bare edge number.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from kalshi_edge.kalshi.models import Orderbook
from kalshi_edge.kalshi.orderbook import (
    effective_prices, simulate_buy_yes, simulate_buy_no,
)
from kalshi_edge.edge.devig import devig, devig_single


@dataclass
class EdgeSignal:
    ticker: str
    side: str                       # "yes" or "no" (which side the edge favours)
    model_fair: float               # model probability of YES
    market_implied: float           # de-vigged market probability of YES
    edge: float                     # model_fair - market_implied
    fillable_size: int              # contracts fillable on `side` at intended size
    slippage: Optional[float]       # VWAP slippage vs best-of-book, or None
    suppressed: bool
    suppression_reason: Optional[str]
    analysis: dict[str, Any]        # GoalModel.analysis record (§3a grounding)


class EdgeEngine:
    def __init__(self, absurd_edge: float = 0.15, max_slippage: float = 0.02,
                 max_age_seconds: float = 900.0):
        self.absurd_edge = absurd_edge
        self.max_slippage = max_slippage
        self.max_age_seconds = max_age_seconds

    def evaluate(
        self,
        ticker: str,
        model_fair: float,
        orderbook: Orderbook,
        analysis: dict,
        fetched_at: datetime,
        intended_size: int,
        now: Optional[datetime] = None,
        market_prices: Optional[dict[str, float]] = None,
        contract_key: Optional[str] = None,
    ) -> EdgeSignal:
        now = now or datetime.now(timezone.utc)

        # --- market-implied YES probability (de-vigged) ---
        if market_prices is not None:
            if contract_key is None:
                raise ValueError("contract_key required when market_prices is given")
            market_implied = devig(market_prices)[contract_key]
        else:
            mid = effective_prices(orderbook).yes_mid
            if mid is None:
                return self._suppressed(ticker, model_fair, None, orderbook,
                                        analysis, "no_market")
            market_implied = devig_single(mid)

        edge = model_fair - market_implied
        side = "yes" if edge > 0 else "no"

        # --- liquidity probe on the favoured side ---
        fill = (simulate_buy_yes(orderbook, intended_size) if side == "yes"
                else simulate_buy_no(orderbook, intended_size))

        def signal(suppressed, reason):
            return EdgeSignal(
                ticker=ticker, side=side, model_fair=model_fair,
                market_implied=market_implied, edge=edge,
                fillable_size=fill.filled, slippage=fill.slippage,
                suppressed=suppressed, suppression_reason=reason, analysis=analysis)

        # --- §3 guardrails, first failure wins ---
        age = (now - fetched_at).total_seconds()
        if age > self.max_age_seconds:
            return signal(True, "stale")
        if abs(edge) > self.absurd_edge:
            return signal(True, "absurd_edge")
        if fill.filled < intended_size:
            return signal(True, "illiquid")
        if fill.slippage is None or fill.slippage > self.max_slippage:
            return signal(True, "illiquid")

        return signal(False, None)

    def _suppressed(self, ticker, model_fair, market_implied, orderbook,
                    analysis, reason) -> EdgeSignal:
        return EdgeSignal(
            ticker=ticker, side="", model_fair=model_fair,
            market_implied=market_implied if market_implied is not None else 0.0,
            edge=0.0, fillable_size=0, slippage=None,
            suppressed=True, suppression_reason=reason, analysis=analysis)
