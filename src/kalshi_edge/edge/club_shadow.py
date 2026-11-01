"""Live shadow pass over club-soccer Kalshi markets.

For every open GAME / TOTAL / BTTS market of a league whose fixture is known (from
football-data ``fixtures.csv``): price it with the club MLE model, evaluate it through
the edge engine (with the learned blend) and return the signals for logging.

Safety rules baked in:
  * a market is skipped unless its fixture has a known kickoff that is at least
    ``min_lead_minutes`` away — an in-play price has the result partly priced in and
    would poison the model-vs-market comparison the blend learns from;
  * fixtures further than ``horizon_days`` out are skipped (stale prices, wasted calls);
  * teams the model has never seen are skipped rather than guessed.
No order is ever placed.
"""
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

from kalshi_edge.config import CLUB_LEAGUES, CLUB_MARKET_KINDS
from kalshi_edge.edge.engine import EdgeEngine, EdgeSignal
from kalshi_edge.kalshi.club_match import event_date, event_suffix, resolve_event
from kalshi_edge.kalshi.market_parse import parse_contract
from kalshi_edge.pricer.pricer import Pricer


def _moneyline_names(markets: list[dict]) -> list[str]:
    names = []
    for m in markets:
        sub = (m.get("yes_sub_title") or "").strip()
        if sub and sub.lower() not in ("tie", "draw") and sub not in names:
            names.append(sub)
    return names


def build_club_signals(client, model, fix_conn, engine: EdgeEngine, *, now: datetime,
                       blend=None, leagues=None, kinds=CLUB_MARKET_KINDS[:3],
                       intended_size: int = 100, min_lead_minutes: int = 30,
                       horizon_days: int = 4, workers: int = 6,
                       max_lead_minutes: int | None = None, variants_for=None):
    """-> (signals, stats). ``client`` needs ``iter_markets`` and ``get_orderbook``.

    Lineup-test hooks (both optional; defaults leave behaviour unchanged):
      * ``max_lead_minutes`` - also skip fixtures kicking off later than this;
      * ``variants_for(home, away, kickoff, event) -> {name: (Pricer, info)} | None`` -
        extra model variants priced off the *same* order book as the base model. Returning
        None skips the fixture (e.g. lineups not out yet). Each signal's ``analysis`` then
        carries ``variant`` ("base" or the name), ``event``, ``kickoff`` (ISO UTC) and the variant's ``info``."""
    stats = defaultdict(int)
    plan = []  # (market, contract, home, away, model_fair, analysis)
    horizon = now + timedelta(days=horizon_days)

    for lg in (leagues or CLUB_LEAGUES):
        tournament = CLUB_LEAGUES[lg]
        by_kind = {k: list(client.iter_markets(series_ticker=f"KX{lg}{k}", status="open"))
                   for k in kinds}
        # teams per event come from the moneyline legs (totals/BTTS don't name them)
        events = defaultdict(list)
        for m in by_kind.get("GAME", []):
            events[event_suffix(m["event_ticker"] if "event_ticker" in m
                                else m["ticker"].rsplit("-", 1)[0])].append(m)
        resolved = {}
        for suffix, ms in events.items():
            names, day = _moneyline_names(ms), event_date(suffix)
            hit = resolve_event(fix_conn, tournament, day, *names[:2]) if len(names) == 2 and day else None
            if hit is None:
                stats["event_unresolved"] += 1
                continue
            row, home_k, away_k = hit
            ko = fix_conn.execute(
                "SELECT kickoff_utc FROM kickoffs WHERE date=? AND home_team=? AND away_team=?",
                (row["date"], row["home_team"], row["away_team"])).fetchone()
            if ko is None:
                stats["no_kickoff"] += 1
                continue
            kickoff = datetime.fromtimestamp(ko[0], tz=timezone.utc)
            if kickoff < now + timedelta(minutes=min_lead_minutes):
                stats["in_play_or_started"] += 1
                continue
            if kickoff > horizon:
                stats["beyond_horizon"] += 1
                continue
            if max_lead_minutes is not None and kickoff > now + timedelta(minutes=max_lead_minutes):
                stats["outside_window"] += 1
                continue
            h, a = row["home_team"], row["away_team"]
            if h not in model.fit.attack or a not in model.fit.attack:
                stats["unknown_team"] += 1
                continue
            extras = {}
            if variants_for is not None:
                extras = variants_for(h, a, kickoff, suffix)
                if extras is None:
                    stats["no_lineup"] += 1
                    continue
            resolved[suffix] = (h, a, home_k, away_k, Pricer.from_model(model, h, a, neutral=False),
                                model.analysis(h, a, neutral=False), extras, suffix, kickoff.isoformat())
        for kind, ms in by_kind.items():
            for m in ms:
                suffix = event_suffix(m["event_ticker"] if "event_ticker" in m
                                      else m["ticker"].rsplit("-", 1)[0])
                if suffix not in resolved:
                    continue
                h, a, hk, ak, pricer, analysis, extras, event, ko_iso = resolved[suffix]
                series = m["ticker"].split("-")[0]
                contract = parse_contract(series, m.get("yes_sub_title") or "", hk, ak)
                if contract is None:
                    stats["unmapped_contract"] += 1
                    continue
                try:
                    fair = pricer.price(contract.name, contract.line)
                except (ValueError, KeyError):
                    stats["pricer_error"] += 1
                    continue
                if variants_for is None:
                    plan.append((m, fair, analysis))
                    continue
                plan.append((m, fair, {**analysis, "variant": "base", "event": event, "kickoff": ko_iso}))
                for name, (vpricer, info) in extras.items():
                    try:
                        plan.append((m, vpricer.price(contract.name, contract.line),
                                     {**analysis, **info, "variant": name, "event": event, "kickoff": ko_iso}))
                    except (ValueError, KeyError):
                        stats["pricer_error"] += 1

    def evaluate(item):
        m, fair, analysis = item
        try:
            ob = client.get_orderbook(m["ticker"])
        except Exception:
            return None
        return engine.evaluate(
            ticker=m["ticker"], model_fair=fair, orderbook=ob, analysis=analysis,
            fetched_at=now, intended_size=intended_size, now=now, blend=blend)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(evaluate, plan))
    signals = [s for s in results if s is not None]
    stats["priced"] = len(signals)
    stats["orderbook_error"] = len(results) - len(signals)
    return signals, dict(stats)
