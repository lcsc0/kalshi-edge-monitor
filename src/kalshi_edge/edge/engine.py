"""Edge engine: model fair prob vs Kalshi de-vigged price, with §3 guardrails.

For a live market the engine computes the model's fair probability (from the
`Pricer`), the market's de-vigged implied probability (from the order book, or
by de-vigging the full contract partition when it is supplied), and the edge
``model_fair - market_implied``. It then applies the design §3 guardrails in
order and emits a structured :class:`EdgeSignal`:

1. **Staleness gate** — refuse if the underlying data is older than ``max_age_seconds``.
2. **Absurd-edge suppression** — if ``abs(edge) > absurd_edge`` treat it as a
   probable model/data error and suppress (do not recommend).
3. **Edge / probability bands** (opt-in via ``from_policy``) — ignore edges below
   ``min_edge`` and bets whose winning-side probability is outside
   ``[min_side_prob, max_side_prob]``.
4. **Liquidity gate** — only surface a signal if the order book can fill the
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
from kalshi_edge.edge.policy import StrategyPolicy, side_prob


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
    raw_model_fair: Optional[float] = None  # model prob before any blend (what the blend learns from)
    entry_price: Optional[float] = None     # VWAP cost per contract of `side` at the intended size


def series_of(ticker: str) -> str:
    """'KXEPLGAME-26MAY24LFCBRE-TIE' -> 'KXEPLGAME' (the blend / scorecard key)."""
    return (ticker or "").split("-")[0]


class EdgeEngine:
    def __init__(self, absurd_edge: float = 0.15, max_slippage: float = 0.02,
                 max_age_seconds: float = 900.0, min_edge: float = 0.0,
                 min_side_prob: float = 0.0, max_side_prob: float = 1.0):
        self.absurd_edge = absurd_edge
        self.max_slippage = max_slippage
        self.max_age_seconds = max_age_seconds
        self.min_edge = min_edge
        self.min_side_prob = min_side_prob
        self.max_side_prob = max_side_prob

    @classmethod
    def from_policy(cls, policy: StrategyPolicy, max_age_seconds: float = 900.0) -> "EdgeEngine":
        """Engine enforcing the shared small-wins policy (edge + probability bands)."""
        return cls(absurd_edge=policy.max_edge, max_slippage=policy.max_slippage,
                   max_age_seconds=max_age_seconds, min_edge=policy.min_edge,
                   min_side_prob=policy.min_side_prob, max_side_prob=policy.max_side_prob)

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
        blend=None,
    ) -> EdgeSignal:
        """``blend`` is an optional ``(series, raw_fair, market_implied) -> fair``
        (see ``edge.blend.BlendTable``). The edge is then measured against the
        *blended* probability, which shrinks to zero where the model has not been
        shown to add information; the raw model probability is kept on the signal."""
        now = now or datetime.now(timezone.utc)
        raw_fair = model_fair

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

        if blend is not None:
            model_fair = blend(series_of(ticker), raw_fair, market_implied)
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
                suppressed=suppressed, suppression_reason=reason, analysis=analysis,
                raw_model_fair=raw_fair, entry_price=fill.avg_price)

        # --- §3 guardrails, first failure wins ---
        age = (now - fetched_at).total_seconds()
        if age > self.max_age_seconds:
            return signal(True, "stale")
        if abs(edge) > self.absurd_edge:
            return signal(True, "absurd_edge")
        if abs(edge) < self.min_edge:
            return signal(True, "below_min_edge")
        if not self.min_side_prob <= side_prob(model_fair, side) <= self.max_side_prob:
            return signal(True, "prob_band")
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
            suppressed=True, suppression_reason=reason, analysis=analysis,
            raw_model_fair=model_fair)
