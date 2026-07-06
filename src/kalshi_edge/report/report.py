"""Headless plain-text / markdown recommendation report (design §9).

A pure function from structured data to a markdown string — no web server, no
side effects — so it is trivially unit-testable and can be read back to the
operator from a phone. It renders today's games, per-market model-fair vs Kalshi
(de-vigged) with edge, the flagged edge signals **with their analysis record**
(the lineup/form/strength drivers, §3a — never a bare edge number), and the
suggested combos with fractional-Kelly sizing. A persistent banner
``UNVALIDATED MODEL — TRADE SMALL`` sits at the top until the backtest clears it.

Expected ``data`` shape::

    {
      "date": "2026-07-06",
      "validated": False,
      "games": [
        {"home": str, "away": str,
         "markets": [{"contract": str, "model_fair": float,
                      "market_implied": float, "edge": float}, ...]},
      ],
      "signals": [EdgeSignal, ...],          # flagged (non-suppressed) edges
      "combos": [{"combo": Combo, "stake": float, "fraction": float}, ...],
    }
"""
from kalshi_edge.edge.engine import EdgeSignal

BANNER = "UNVALIDATED MODEL — TRADE SMALL"


def _fmt(x: float, nd: int = 2) -> str:
    return f"{x:.{nd}f}"


def _signed(x: float, nd: int = 3) -> str:
    return f"{x:+.{nd}f}"


def _market_table(markets: list[dict]) -> list[str]:
    lines = ["| Contract | Model fair | Kalshi (de-vig) | Edge |",
             "| --- | --- | --- | --- |"]
    for m in markets:
        lines.append(
            f"| {m['contract']} | {_fmt(m['model_fair'])} | "
            f"{_fmt(m['market_implied'])} | {_signed(m['edge'])} |")
    return lines


def _analysis_block(analysis: dict) -> list[str]:
    """Render the §3a grounding drivers behind a flagged signal."""
    lines: list[str] = []
    eg = analysis.get("expected_goals")
    if eg:
        lines.append(f"  - Expected goals: {analysis.get('home', 'home')} "
                     f"{_fmt(eg['home'])} vs {analysis.get('away', 'away')} "
                     f"{_fmt(eg['away'])}")
    strength = analysis.get("strength")
    if strength:
        for team, s in strength.items():
            lines.append(f"  - Strength {team}: attack {_fmt(s['attack'])}, "
                         f"defense {_fmt(s['defense'])}")
    op = analysis.get("outcome_probs")
    if op:
        lines.append("  - Model outcome probs: "
                     + ", ".join(f"{k} {_fmt(v)}" for k, v in op.items()))
    return lines


def _signal_block(sig: EdgeSignal) -> list[str]:
    lines = [
        f"- **{sig.ticker}** — buy **{sig.side.upper()}** | model {_fmt(sig.model_fair)} "
        f"vs market {_fmt(sig.market_implied)} | edge {_signed(sig.edge)} | "
        f"fillable {sig.fillable_size}",
        "  Why (analysis drivers):",
    ]
    lines.extend(_analysis_block(sig.analysis))
    return lines


def _combo_block(entry: dict) -> list[str]:
    combo = entry["combo"]
    legs = " + ".join(
        f"{lg.game_id}:{lg.leg[0]}" + (f" {lg.leg[1]}" if len(lg.leg) > 1 else "")
        for lg in combo.legs)
    return [
        f"- {legs}",
        f"  - Joint hit prob: {_fmt(combo.joint_prob)} | "
        f"payout multiplier: {_fmt(combo.multiplier)}x",
        f"  - Suggested stake ({int(entry['fraction'] * 100)}% Kelly): "
        f"${_fmt(entry['stake'])}",
    ]


def render_report(data: dict) -> str:
    lines: list[str] = []
    if not data.get("validated", False):
        lines.append(f"**{BANNER}**")
        lines.append("")
    lines.append(f"# Kalshi Edge Report — {data.get('date', '')}")
    lines.append("")

    lines.append("## Today's games")
    games = data.get("games", [])
    if not games:
        lines.append("_No soccer games found for today._")
    for g in games:
        lines.append("")
        lines.append(f"### {g['home']} vs {g['away']}")
        lines.extend(_market_table(g.get("markets", [])))

    lines.append("")
    lines.append("## Flagged edges")
    signals = data.get("signals", [])
    if not signals:
        lines.append("_No edges cleared the guardrails._")
    for sig in signals:
        lines.extend(_signal_block(sig))

    lines.append("")
    lines.append("## Suggested combos (fractional Kelly)")
    combos = data.get("combos", [])
    if not combos:
        lines.append("_No combo met the joint-probability target._")
    for entry in combos:
        lines.extend(_combo_block(entry))

    return "\n".join(lines) + "\n"
