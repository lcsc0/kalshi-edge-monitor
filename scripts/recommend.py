"""Recommendation-surface entrypoint (design §9): model -> pricer -> edge ->
combo -> report.

`build_report_data` is the offline-testable core: given each game's `Pricer`, its
model `analysis` record, and the live market specs (ticker + order book + a
contract descriptor), it runs the edge engine's §3 guardrails, keeps the flagged
edges, searches for the best fractional-Kelly-sized combo, and returns the data
dict `report.render_report` turns into markdown. `main()` wires the live Kalshi
client for on-demand use from a phone.

A "market spec" is::

    {
      "ticker": str,
      "contract": str,            # pricer contract name, e.g. "home", "over"
      "line": float | None,       # for totals / team totals
      "label": str,               # human label for the report row
      "orderbook": Orderbook,
      "fetched_at": datetime,
      "market_prices": dict | None,   # full partition for de-vig (optional)
      "contract_key": str | None,     # key within market_prices (optional)
    }
"""
from datetime import datetime, timezone

from kalshi_edge.kalshi.orderbook import effective_prices
from kalshi_edge.edge.engine import EdgeEngine
from kalshi_edge.edge.sizing import size_bet
from kalshi_edge.combo.optimizer import ComboLeg, optimize
from kalshi_edge.report.report import render_report


def _buy_cost(orderbook, side: str, fallback: float) -> float:
    """Cost to buy one contract on `side` (yes_ask, or 1 - yes_bid for no)."""
    ep = effective_prices(orderbook)
    if side == "yes" and ep.yes_ask is not None:
        return ep.yes_ask
    if side == "no" and ep.yes_bid is not None:
        return 1.0 - ep.yes_bid
    return fallback


def build_report_data(
    games: list[dict],
    *,
    engine: EdgeEngine,
    now: datetime,
    bankroll: float,
    fraction: float = 0.25,
    target_prob: float = 0.5,
    intended_size: int = 100,
    per_combo_cap: float | None = None,
    per_game_cap: float | None = None,
    per_day_cap: float | None = None,
    validated: bool = False,
    date: str = "",
    max_legs: int = 4,
) -> dict:
    report_games = []
    signals = []
    combo_legs: list[ComboLeg] = []

    for g in games:
        pricer = g["pricer"]
        analysis = g["analysis"]
        game_id = f"{g['home']}-{g['away']}"
        market_rows = []
        for spec in g.get("markets", []):
            line = spec.get("line")
            model_fair = pricer.price(spec["contract"], line)
            sig = engine.evaluate(
                ticker=spec["ticker"], model_fair=model_fair,
                orderbook=spec["orderbook"], analysis=analysis,
                fetched_at=spec["fetched_at"], intended_size=intended_size,
                now=now, market_prices=spec.get("market_prices"),
                contract_key=spec.get("contract_key"))
            market_rows.append({
                "contract": spec.get("label", spec["contract"]),
                "model_fair": model_fair,
                "market_implied": sig.market_implied,
                "edge": sig.edge,
            })
            if not sig.suppressed:
                signals.append(sig)
                leg = (spec["contract"],) if line is None else (spec["contract"], line)
                cost = _buy_cost(spec["orderbook"], sig.side, sig.market_implied)
                combo_legs.append(ComboLeg(
                    game_id=game_id, pricer=pricer, leg=leg,
                    model_fair=model_fair, market_price=cost, edge=sig.edge))
        report_games.append({"home": g["home"], "away": g["away"],
                             "markets": market_rows})

    combos = []
    best = optimize(combo_legs, target_prob=target_prob, max_legs=max_legs)
    if best is not None:
        combo_price = 1.0 / best.multiplier
        stake = size_bet(best.joint_prob, combo_price, bankroll,
                         fraction=fraction, per_combo_cap=per_combo_cap,
                         per_game_cap=per_game_cap, per_day_cap=per_day_cap)
        combos.append({"combo": best, "stake": stake, "fraction": fraction})

    return {
        "date": date,
        "validated": validated,
        "games": report_games,
        "signals": signals,
        "combos": combos,
    }


def build_report(games: list[dict], **kwargs) -> str:
    return render_report(build_report_data(games, **kwargs))


def main() -> None:  # pragma: no cover - live wiring
    print("**UNVALIDATED MODEL — TRADE SMALL**\n")
    print("recommend.py wires GoalModel -> Pricer -> EdgeEngine -> combo -> report.")
    print("Live use needs a ticker->contract map (SP1 market parsing) to build the")
    print("`games` specs; call build_report_data(...) with those specs to render.")
    _ = (EdgeEngine, datetime.now(timezone.utc))


if __name__ == "__main__":
    main()
