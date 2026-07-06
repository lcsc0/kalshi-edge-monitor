"""Parse live Kalshi soccer markets into Pricer legs + matchups.

Single source of truth for the Kalshi-market -> Pricer-contract mapping, shared
by the live recommendation surface (``scripts/recommend.py``) and the backtest
(``kalshi_edge.backtest.replay`` re-imports ``ContractSpec`` / ``parse_contract``).

A per-match *event* groups several contract *markets*. Totals/BTTS subtitles
("Over 1.5 goals scored") don't name the teams — only the moneyline legs do
("Reg Time: Argentina") — so the matchup is inferred from those legs rather than
by splitting an event-title string whose exact schema we can't observe here.
"""
from dataclasses import dataclass
import re


# --------------------------------------------------------------------------- #
# Data types
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class ContractSpec:
    """A Pricer leg: ``name`` + optional ``line`` (see ``Pricer.price``).

    ``line`` is a float for totals/team-totals, an ``(h, a)`` tuple for exact
    score, or ``None`` for moneyline/BTTS.
    """
    name: str
    line: object = None


@dataclass(frozen=True)
class Matchup:
    home: str
    away: str
    neutral: bool = True


@dataclass(frozen=True)
class ParsedMarket:
    ticker: str
    contract: ContractSpec
    label: str


# --------------------------------------------------------------------------- #
# Subtitle -> contract
# --------------------------------------------------------------------------- #

_OVER_RE = re.compile(r"over\s+(\d+(?:\.\d+)?)", re.I)
_UNDER_RE = re.compile(r"under\s+(\d+(?:\.\d+)?)", re.I)
_SCORE_RE = re.compile(r"(\d+)\s*-\s*(\d+)")

_MONEYLINE_SERIES = ("KXWCGAME", "KXWCMATCHUP", "KXWCTEAMH2H")


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _series_key(series: str) -> str:
    return (series or "").upper().split("-")[0]


def parse_contract(series: str, subtitle: str, home: str, away: str) -> ContractSpec | None:
    """Best-effort map of a Kalshi soccer market to a Pricer leg.

    Returns ``None`` for market types outside the SP2c Pricer surface
    (spreads, player goals) — the caller records them as *unmapped*.
    """
    key = _series_key(series)
    sub = (subtitle or "").strip()
    low = sub.lower()

    if key in _MONEYLINE_SERIES:
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
        side = ("home" if _norm(home) in _norm(sub)
                else "away" if _norm(away) in _norm(sub) else None)
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

    # KXWCSPREAD, KXWCPLAYERGOALS and anything unknown are not on the Pricer surface.
    return None


# --------------------------------------------------------------------------- #
# Market fields
# --------------------------------------------------------------------------- #

def market_subtitle(market: dict) -> str:
    """The text describing what a market's YES side pays."""
    return (market.get("yes_sub_title") or market.get("subtitle")
            or market.get("title") or "")


def market_series(market: dict) -> str:
    return market.get("series_ticker") or (market.get("ticker") or "").split("-")[0]


# --------------------------------------------------------------------------- #
# Matchup inference (from the moneyline legs)
# --------------------------------------------------------------------------- #

def _moneyline_team(market: dict) -> str | None:
    if _series_key(market_series(market)) not in _MONEYLINE_SERIES:
        return None
    target = re.sub(r"(?i)reg\s*time\s*:", "", market_subtitle(market)).strip()
    if not target or target.lower() in ("draw", "tie"):
        return None
    return target


def infer_matchup(markets: list[dict], neutral: bool = True) -> Matchup | None:
    """Two teams from the event's moneyline legs (first-seen order).

    Home/away order is cosmetic on neutral ground; ``neutral`` defaults True for
    World Cup fixtures. Returns ``None`` if fewer than two teams are found.
    """
    seen: list[str] = []
    for m in markets:
        team = _moneyline_team(m)
        if team and team not in seen:
            seen.append(team)
        if len(seen) == 2:
            return Matchup(seen[0], seen[1], neutral=neutral)
    return None


# --------------------------------------------------------------------------- #
# Team-name resolution against the model roster
# --------------------------------------------------------------------------- #

# Kalshi display name -> the string used in the international-results dataset.
_ALIASES = {
    "usa": "United States",
    "united states of america": "United States",
    "south korea": "Korea Republic",
    "north korea": "Korea DPR",
    "ivory coast": "Côte d'Ivoire",
    "cape verde": "Cabo Verde",
    "czech republic": "Czechia",
    "china": "China PR",
}


def resolve_team(name: str, roster) -> str | None:
    """Map a Kalshi team string to its key in ``roster`` (or ``None``).

    Tries exact, case/space-normalized, and a small alias table. ``roster`` is
    any container of the model's team keys (e.g. ``model.teams``).
    """
    if name in roster:
        return name
    target = _norm(name)
    by_norm = {_norm(t): t for t in roster}
    if target in by_norm:
        return by_norm[target]
    alias = _ALIASES.get(target)
    if alias and alias in roster:
        return alias
    if alias and _norm(alias) in by_norm:
        return by_norm[_norm(alias)]
    return None


# --------------------------------------------------------------------------- #
# Market -> ParsedMarket
# --------------------------------------------------------------------------- #

def parse_market(market: dict, matchup: Matchup) -> ParsedMarket | None:
    """Map one live market dict to a ``ParsedMarket`` or ``None`` if unmapped."""
    sub = market_subtitle(market)
    spec = parse_contract(market_series(market), sub, matchup.home, matchup.away)
    if spec is None:
        return None
    return ParsedMarket(ticker=market["ticker"], contract=spec, label=sub or spec.name)
