"""LLM lineup adjustment (the thing the paper test is really about).

Given the model's expected goals and the confirmed XIs (plus who is missing versus the
usual XI where we have history), ask Claude for two multipliers on expected goals. The
reply is clamped; any failure returns None so a flaky call just drops that variant for
that game instead of poisoning the log. No order is ever placed from this output.
"""
import json
import os
import re

import httpx

from kalshi_edge.config import anthropic_api_key

API_URL = "https://api.anthropic.com/v1/messages"
DEFAULT_MODEL = "claude-sonnet-5-5"
CLAMP = (0.75, 1.25)

SYSTEM = (
    "You adjust football (soccer) expected-goals estimates for confirmed starting lineups. "
    "You are given a statistical model's expected goals for each team and the starting XIs. "
    "Return ONLY a JSON object: "
    '{"home_goals_mult": <number>, "away_goals_mult": <number>, "reason": "<one sentence>"}. '
    "A multiplier scales that team's expected goals (1.0 = no change). Account for both the "
    "team's own attacking absences and the opponent's defensive/goalkeeper absences. The "
    "model already knows team strength, so only move away from 1.0 when the lineup carries "
    "clear, material information (a key player missing, heavy rotation). When unsure, stay "
    f"near 1.0. Stay within {CLAMP[0]}-{CLAMP[1]}."
)


def build_prompt(ctx: dict) -> str:
    def side(name, lineup, missing):
        xi = ", ".join(f"{n} ({p})" for _, n, p in lineup.players)
        miss = ", ".join(f"{m['name']} ({m['pos']}, started {m['share']:.0%} of recent games)"
                         for m in missing) or "none known (no usable history)"
        return f"{name} [{lineup.formation or '?'}]: {xi}\n  Usual starters missing: {miss}"
    return (f"{ctx['league']}: {ctx['home']} (home) vs {ctx['away']}, kickoff {ctx['kickoff']}.\n"
            f"Model expected goals: {ctx['home']} {ctx['xg_home']:.2f}, {ctx['away']} {ctx['xg_away']:.2f}.\n"
            f"{side(ctx['home'], ctx['home_lineup'], ctx['home_missing'])}\n"
            f"{side(ctx['away'], ctx['away_lineup'], ctx['away_missing'])}")


def parse_reply(text: str) -> tuple[float, float, str] | None:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        d = json.loads(m.group(0))
        h, a = float(d["home_goals_mult"]), float(d["away_goals_mult"])
    except (ValueError, KeyError, TypeError):
        return None
    if not all(x == x and x > 0 for x in (h, a)):   # NaN / non-positive
        return None
    lo, hi = CLAMP
    return min(max(h, lo), hi), min(max(a, lo), hi), str(d.get("reason", ""))[:300]


class LineupLLM:
    def __init__(self, api_key: str | None = None, model: str | None = None,
                 http: httpx.Client | None = None):
        self.api_key = api_key or anthropic_api_key()
        self.model = model or os.environ.get("LINEUP_LLM_MODEL") or DEFAULT_MODEL
        self._http = http or httpx.Client(timeout=60.0)

    def adjust(self, ctx: dict) -> tuple[float, float, str] | None:
        try:
            resp = self._http.post(
                API_URL,
                headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
                json={"model": self.model, "max_tokens": 300,
                      "system": SYSTEM, "messages": [{"role": "user", "content": build_prompt(ctx)}]})
            resp.raise_for_status()
            text = "".join(b.get("text", "") for b in resp.json().get("content", []))
        except (httpx.HTTPError, ValueError):
            return None
        return parse_reply(text)
