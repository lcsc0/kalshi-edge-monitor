"""Map Kalshi club-soccer events onto rows of the club results DB.

Kalshi spells clubs its own way ("Atletico", "Man United"); football-data uses
"Ath Madrid", "Man United". Rather than maintain a global alias table, resolve
each event against only the fixtures played that day: with ~10 candidate matches
a fuzzy name score is unambiguous, and the DB row also supplies the true
home/away orientation and kickoff time.
"""
import re
import unicodedata
from datetime import date
from difflib import SequenceMatcher

_MONTHS = {m: i for i, m in enumerate(
    ("JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"), 1)}
_EVENT_RE = re.compile(r"^(\d{2})([A-Z]{3})(\d{2})")
_TITLE_RE = re.compile(r"^(.*?)\s+vs\.?\s+(.*?)(?:\s+Winner\?)?$", re.I)
_NOISE = re.compile(r"\b(fc|cf|afc|sc|ac|as|ssc|rc|rcd|ud|sv|vfb|vfl|fsv|1\.|ca|club|de|the)\b")


def event_date(event_ticker: str) -> date | None:
    """'KXEPLGAME-26MAY24LFCBRE' -> 2026-05-24 (date as encoded by Kalshi)."""
    part = event_ticker.split("-", 1)[-1]
    m = _EVENT_RE.match(part)
    if not m or m.group(2) not in _MONTHS:
        return None
    return date(2000 + int(m.group(1)), _MONTHS[m.group(2)], int(m.group(3)))


def event_suffix(event_ticker: str) -> str:
    """Series-independent id: 'KXEPLGAME-26MAY24LFCBRE' -> '26MAY24LFCBRE'."""
    return event_ticker.split("-", 1)[-1]


def title_teams(title: str) -> tuple[str, str] | None:
    """'Liverpool vs Brentford Winner?' -> ('Liverpool', 'Brentford')."""
    m = _TITLE_RE.match((title or "").strip())
    if not m or not m.group(1) or not m.group(2):
        return None
    return m.group(1).strip(), m.group(2).strip()


def _norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9. ]", " ", s)
    s = _NOISE.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


# football-data abbreviation (normalised) -> other spellings Kalshi may use.
_ALIASES = {
    "ath madrid": ("atletico madrid", "atletico"),
    "ath bilbao": ("athletic club", "athletic bilbao"),
    "paris sg": ("paris saint germain", "psg", "paris saint-germain"),
    "sociedad": ("real sociedad",),
    "betis": ("real betis",),
    "vallecano": ("rayo vallecano",),
    "espanol": ("espanyol",),
    "celta": ("celta vigo",),
    "man city": ("manchester city",),
    "man united": ("manchester united",),
    "nott m forest": ("nottingham forest", "nottm forest"),
    "spurs": ("tottenham", "tottenham hotspur"),
    "wolves": ("wolverhampton", "wolverhampton wanderers"),
    "newcastle": ("newcastle united",),
    "west ham": ("west ham united",),
    "leeds": ("leeds united",),
    "m gladbach": ("monchengladbach", "borussia monchengladbach", "gladbach"),
    "ein frankfurt": ("eintracht frankfurt", "frankfurt"),
    "leverkusen": ("bayer leverkusen", "bayer 04 leverkusen"),
    "dortmund": ("borussia dortmund",),
    "bayern munich": ("bayern", "bayern munchen"),
    "fc koln": ("koln", "cologne", "1. fc koln", "1. fc cologne", "fc cologne"),
    "mainz": ("mainz 05", "fsv mainz 05"),
    "hoffenheim": ("tsg hoffenheim", "tsg 1899 hoffenheim"),
    "st pauli": ("fc st. pauli", "st. pauli"),
    "inter": ("inter milan", "internazionale"),
    "milan": ("ac milan",),
    "verona": ("hellas verona",),
    "roma": ("as roma",),
    "napoli": ("ssc napoli",),
    "marseille": ("olympique marseille", "olympique de marseille"),
    "lyon": ("olympique lyonnais", "olympique lyon"),
    "st etienne": ("saint-etienne", "saint etienne"),
    "sp lisbon": ("sporting cp", "sporting lisbon", "sporting"),
    "sp braga": ("braga", "sporting braga"),
    "porto": ("fc porto",),
    "benfica": ("sl benfica",),
    "ajax": ("ajax amsterdam",),
    "psv eindhoven": ("psv",),
    "az alkmaar": ("az",),
    "sheffield united": ("sheffield utd",),
    "sheffield weds": ("sheffield wednesday",),
    "qpr": ("queens park rangers",),
    "west brom": ("west bromwich albion", "west bromwich"),
    "norwich": ("norwich city",),
    "stoke": ("stoke city",),
    "swansea": ("swansea city",),
    "cardiff": ("cardiff city",),
    "hull": ("hull city",),
    "preston": ("preston north end",),
    "coventry": ("coventry city",),
    "leicester": ("leicester city",),
    "brighton": ("brighton and hove albion", "brighton hove albion"),
    "bournemouth": ("afc bournemouth",),
}


# Lookups use normalised names (which strip "fc", "1." ...), so normalise the table too.
_ALIASES_N = {_norm(k): tuple(_norm(v) for v in vs) for k, vs in _ALIASES.items()}


def name_score_plain(na: str, nb: str) -> float:
    """Containment-aware similarity of two already-normalised names."""
    ratio = SequenceMatcher(None, na, nb).ratio()
    short, long_ = sorted((na, nb), key=len)
    if len(short) >= 4 and (long_.startswith(short) or short in long_.split()):
        ratio = max(ratio, 0.85)
    return ratio


def name_score(a: str, b: str) -> float:
    """0..1 similarity; a prefix/containment match ('Atletico' ~ 'Atletico Madrid')
    scores high even though the raw ratio is low."""
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    for x, y in ((na, nb), (nb, na)):
        if y in _ALIASES_N.get(x, ()):
            return 1.0
        if any(name_score_plain(alt, y) >= 0.85 for alt in _ALIASES_N.get(x, ())):
            return 0.9
    return name_score_plain(na, nb)


def resolve_event(conn, tournament: str, day: date, kalshi_a: str, kalshi_b: str,
                  min_score: float = 0.6):
    """Find the DB fixture for a Kalshi pairing on ``day`` (Kalshi's date can be a
    day off for late kickoffs, so +/-1 day is searched, exact day preferred).

    Returns ``(row, home_k, away_k)`` where ``row`` is the matches row and
    ``home_k``/``away_k`` are the *Kalshi* spellings oriented to the DB's home/away
    (needed to parse subtitles like "Arsenal wins by over 1.5 goals"); or None.
    """
    best = None
    for off in (0, -1, 1):
        d = date.fromordinal(day.toordinal() + off).isoformat()
        for r in conn.execute(
                "SELECT date, home_team, away_team FROM matches WHERE date=? AND tournament=?",
                (d, tournament)):
            straight = min(name_score(kalshi_a, r["home_team"]), name_score(kalshi_b, r["away_team"]))
            swapped = min(name_score(kalshi_b, r["home_team"]), name_score(kalshi_a, r["away_team"]))
            score, orient = max((straight, 0), (swapped, 1))
            if score >= min_score and (best is None or score - 0.001 * abs(off) > best[0]):
                best = (score - 0.001 * abs(off), r, orient)
        if best and off == 0:
            break
    if best is None:
        return None
    _, row, orient = best
    home_k, away_k = (kalshi_a, kalshi_b) if orient == 0 else (kalshi_b, kalshi_a)
    return row, home_k, away_k
