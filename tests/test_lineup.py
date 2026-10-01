from datetime import datetime, timezone

import httpx
import respx

from kalshi_edge.data.cache import connect
from kalshi_edge.lineup.adjust import TEAM_CAP, goal_multipliers, team_effects
from kalshi_edge.lineup.history import ensure_history, missing_regulars, record_lineup, regulars
from kalshi_edge.lineup.lineups import Lineup, find_fixture, parse_lineups
from kalshi_edge.lineup.llm import API_URL, LineupLLM, parse_reply


def _lineup(ids, pos="M"):
    return Lineup(1, "T", "4-4-2", tuple((i, f"p{i}", pos if i != 1 else "G") for i in ids))


def _api_entry(team_id, n=11):
    return {"team": {"id": team_id, "name": f"T{team_id}"}, "formation": "4-3-3",
            "startXI": [{"player": {"id": i, "name": f"p{i}", "pos": "M"}} for i in range(n)]}


def test_parse_lineups_requires_full_xi():
    got = parse_lineups([_api_entry(1), _api_entry(2, n=3)])
    assert list(got) == [1] and len(got[1].players) == 11
    assert parse_lineups([]) == {}


def test_find_fixture_matches_names_and_time_window():
    ko = datetime(2026, 10, 10, 14, 0, tzinfo=timezone.utc)
    fx = [{"fixture": {"id": 7, "timestamp": int(ko.timestamp())},
           "teams": {"home": {"id": 1, "name": "Manchester United"}, "away": {"id": 2, "name": "Tottenham"}}},
          {"fixture": {"id": 8, "timestamp": int(ko.timestamp()) + 86400},
           "teams": {"home": {"id": 1, "name": "Manchester United"}, "away": {"id": 2, "name": "Tottenham"}}}]
    assert find_fixture(fx, "Man United", "Spurs", ko)["fixture"]["id"] == 7
    assert find_fixture(fx, "Arsenal", "Chelsea", ko) is None


def test_regulars_need_min_games_and_exclude_rotation():
    conn = connect()
    ensure_history(conn)
    core = list(range(10))
    for g in range(4):
        # 10 core players every game, an 11th who differs each game
        record_lineup(conn, "T", g, f"2026-09-0{g + 1}", _lineup(core + [100 + g]))
    reg = regulars(conn, "T", "2026-10-01")
    assert {r["id"] for r in reg} == set(core)
    assert regulars(conn, "T", "2026-09-03") == []           # only 2 games logged before -> no regulars yet
    today = _lineup(core[:-1] + [200])                       # player 9 missing
    assert [m["id"] for m in missing_regulars(conn, "T", today, "2026-10-01")] == [9]


def test_effects_by_position_capped_and_neutral_when_nothing_missing():
    assert goal_multipliers([], []) == (1.0, 1.0)
    fwd = [{"pos": "F", "share": 1.0}]
    gk = [{"pos": "G", "share": 1.0}]
    assert team_effects(fwd) == (0.95, 1.0)
    assert team_effects(gk) == (1.0, 1.06)
    h, a = goal_multipliers(fwd, gk)          # home misses a striker, away misses its keeper
    assert h == 0.95 * 1.06 and a == 1.0 * 1.0 and h > a - 0.1
    assert team_effects([{"pos": "F", "share": 1.0}] * 20)[0] == 1.0 - TEAM_CAP


def test_llm_reply_parsing_clamps_and_rejects_garbage():
    assert parse_reply('Sure: {"home_goals_mult": 0.9, "away_goals_mult": 1.5, "reason": "x"}') == (0.9, 1.25, "x")
    assert parse_reply("no json") is None
    assert parse_reply('{"home_goals_mult": "a", "away_goals_mult": 1}') is None
    assert parse_reply('{"home_goals_mult": -1, "away_goals_mult": 1}') is None


@respx.mock
def test_llm_adjust_calls_api_and_survives_errors():
    ctx = {"league": "L", "home": "A", "away": "B", "kickoff": "k", "xg_home": 1.5, "xg_away": 1.1,
           "home_lineup": _lineup(range(11)), "away_lineup": _lineup(range(11)),
           "home_missing": [{"name": "Star", "pos": "F", "share": 0.9}], "away_missing": []}
    route = respx.post(API_URL).mock(return_value=httpx.Response(200, json={"content": [
        {"type": "text", "text": '{"home_goals_mult": 0.85, "away_goals_mult": 1.0, "reason": "no striker"}'}]}))
    out = LineupLLM(api_key="k").adjust(ctx)
    assert out == (0.85, 1.0, "no striker")
    sent = route.calls[0].request
    assert sent.headers["x-api-key"] == "k" and b"Star" in sent.content
    route.mock(return_value=httpx.Response(500))
    assert LineupLLM(api_key="k").adjust(ctx) is None
