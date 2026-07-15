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
from collections import defaultdict
from datetime import date, datetime, timezone

from kalshi_edge.kalshi.orderbook import effective_prices
from kalshi_edge.kalshi.soccer import todays_soccer_markets
from kalshi_edge.kalshi.market_parse import (
    infer_matchup, parse_market, parse_player_prop, resolve_team,
)
from kalshi_edge.model.player_props import player_team, player_goal_prob
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
            # Player props (and any non-matrix contract) carry a precomputed
            # `model_fair`; matrix contracts are priced from the joint matrix.
            model_fair = (spec["model_fair"] if spec.get("model_fair") is not None
                          else pricer.price(spec["contract"], line))
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
                # Only joint-matrix legs can enter same-game combos (the combo
                # sums the shared goal matrix); player props are standalone.
                if spec.get("combinable", True):
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


def build_games(client, model, *, series_tickers: list[str], target: date,
                now: datetime, conn=None, since: str | None = None
                ) -> tuple[list[dict], list[str]]:
    """Turn today's live Kalshi soccer markets into `build_report_data` specs.

    Groups each event's markets into one game, infers the matchup from the
    moneyline legs, resolves both teams against the model roster, builds a
    `Pricer` + analysis record, maps each market to a Pricer contract and pulls
    its order book. Player-goals props are priced off `model.player_props` using
    the goals `conn` (skipped if no `conn` is supplied). Returns `(games,
    skipped)` where `skipped` lists events or markets we could not map so the
    operator sees the coverage gaps rather than silent drops.
    """
    from kalshi_edge.pricer.pricer import Pricer  # local: keeps import graph flat
    from kalshi_edge.kalshi.market_parse import market_series, market_subtitle

    by_event: dict[str, list[dict]] = defaultdict(list)
    for market in todays_soccer_markets(client, series_tickers, target):
        by_event[market.get("event_ticker") or market.get("ticker")].append(market)

    games: list[dict] = []
    skipped: list[str] = []
    for event_ticker, markets in by_event.items():
        matchup = infer_matchup(markets)
        if matchup is None:
            skipped.append(f"{event_ticker}: no moneyline legs to infer teams")
            continue
        home = resolve_team(matchup.home, model.teams)
        away = resolve_team(matchup.away, model.teams)
        if home is None or away is None:
            unknown = matchup.home if home is None else matchup.away
            skipped.append(f"{event_ticker}: team not in model roster ({unknown!r})")
            continue

        pricer = Pricer.from_model(model, home, away, neutral=matchup.neutral)
        analysis = model.analysis(home, away, neutral=matchup.neutral)
        lam_home, lam_away = model.expected_goals(home, away, neutral=matchup.neutral)
        specs = []
        for market in markets:
            parsed = parse_market(market, matchup)
            if parsed is not None:
                specs.append({
                    "ticker": parsed.ticker,
                    "contract": parsed.contract.name,
                    "line": parsed.contract.line,
                    "label": parsed.label,
                    "orderbook": client.get_orderbook(parsed.ticker),
                    "fetched_at": now,
                })
                continue
            prop = parse_player_prop(market_series(market), market_subtitle(market))
            if prop is not None and conn is not None:
                player, threshold = prop
                team = player_team(conn, player, [home, away], since=since)
                if team is not None:
                    team_lambda = lam_home if team == home else lam_away
                    fair = player_goal_prob(conn, player, team, team_lambda, threshold, since=since)
                    specs.append({
                        "ticker": market["ticker"],
                        "contract": f"player:{player}:{threshold}+",
                        "line": None, "label": market_subtitle(market),
                        "model_fair": fair, "combinable": False,
                        "orderbook": client.get_orderbook(market["ticker"]),
                        "fetched_at": now,
                    })
                    continue
                skipped.append(f"{market.get('ticker')}: player {player!r} not in goals data")
                continue
            skipped.append(f"{market.get('ticker')}: unmapped contract")
        if specs:
            games.append({"home": home, "away": away, "pricer": pricer,
                          "analysis": analysis, "markets": specs})
    return games, skipped


def main() -> None:  # pragma: no cover - live wiring
    from kalshi_edge.config import KALSHI_BASE_URL, SOCCER_SERIES_TICKERS
    from kalshi_edge.kalshi.http import KalshiHTTP
    from kalshi_edge.kalshi.client import KalshiClient
    from kalshi_edge.data.cache import connect
    from kalshi_edge.model.goal_model import GoalModel

    DB = "data/football.sqlite"
    now = datetime.now(timezone.utc)
    today = now.date()
    ref_date = today.isoformat()

    try:
        conn = connect(DB)
        model = GoalModel.from_db(conn, ref_date=ref_date, since="2016-01-01")
    except Exception as exc:  # noqa: BLE001 - degrade to a clear message
        print("**UNVALIDATED MODEL — TRADE SMALL**\n")
        print(f"Could not build the goal model from {DB}: {exc}")
        print("Run `python scripts/build_db.py` first.")
        return

    client = KalshiClient(http=KalshiHTTP(base_url=KALSHI_BASE_URL))
    try:
        games, skipped = build_games(client, model, series_tickers=SOCCER_SERIES_TICKERS,
                                     target=today, now=now, conn=conn, since="2016-01-01")
    except Exception as exc:  # noqa: BLE001 - network / API unreachable
        print("**UNVALIDATED MODEL — TRADE SMALL**\n")
        print(f"Could not reach Kalshi live markets: {exc}")
        return

    engine = EdgeEngine()
    print(build_report(games, engine=engine, now=now, bankroll=1000.0,
                       date=ref_date, validated=False))
    if skipped:
        print("\nSkipped (unmapped / unknown team):")
        for line in skipped:
            print(f"  - {line}")


if __name__ == "__main__":
    main()
