from kalshi_edge.kalshi.market_parse import (
    ContractSpec, Matchup, parse_contract, infer_matchup, resolve_team,
    parse_market,
)


# --- parse_contract (moved from backtest; behaviour preserved) ---

def test_moneyline_team_and_draw():
    assert parse_contract("KXWCGAME", "Reg Time: Argentina", "Argentina", "Colombia") == ContractSpec("home")
    assert parse_contract("KXWCGAME", "Reg Time: Colombia", "Argentina", "Colombia") == ContractSpec("away")
    assert parse_contract("KXWCGAME", "Reg Time: Draw", "Argentina", "Colombia") == ContractSpec("draw")


def test_totals_over_under_with_reg_time_prefix():
    assert parse_contract("KXWCTOTAL", "Reg Time: Over 1.5 goals scored", "A", "B") == ContractSpec("over", 1.5)
    assert parse_contract("KXWCTOTAL", "Under 3.5 goals scored", "A", "B") == ContractSpec("under", 3.5)


def test_btts_yes_no():
    assert parse_contract("KXWCBTTS", "Yes", "A", "B") == ContractSpec("btts")
    assert parse_contract("KXWCBTTS", "No", "A", "B") == ContractSpec("btts_no")


def test_team_total_and_score():
    assert parse_contract("KXWCTEAMTOTAL", "Argentina Over 1.5", "Argentina", "Colombia") == ContractSpec("home_over", 1.5)
    assert parse_contract("KXWCSCORE", "2-1", "A", "B") == ContractSpec("exact", (2, 1))


def test_unsupported_series_returns_none():
    assert parse_contract("KXWCSPREAD", "France wins by more than 1.5 goals", "France", "B") is None
    assert parse_contract("KXWCPLAYERGOALS", "Lionel Messi: 1+", "Argentina", "B") is None


# --- matchup inference from the moneyline legs ---

def _moneyline_markets():
    return [
        {"ticker": "T1", "series_ticker": "KXWCGAME", "yes_sub_title": "Reg Time: Argentina"},
        {"ticker": "T2", "series_ticker": "KXWCGAME", "yes_sub_title": "Reg Time: Draw"},
        {"ticker": "T3", "series_ticker": "KXWCGAME", "yes_sub_title": "Reg Time: Colombia"},
        {"ticker": "T4", "series_ticker": "KXWCTOTAL", "yes_sub_title": "Over 2.5 goals scored"},
    ]


def test_infer_matchup_from_moneyline():
    m = infer_matchup(_moneyline_markets())
    assert m == Matchup("Argentina", "Colombia", neutral=True)


def test_infer_matchup_none_when_no_moneyline():
    assert infer_matchup([{"ticker": "T", "series_ticker": "KXWCTOTAL",
                           "yes_sub_title": "Over 2.5 goals scored"}]) is None


# --- team-name resolution against the model roster ---

def test_resolve_team_exact_and_alias_and_case():
    roster = {"United States", "Argentina", "South Korea"}
    assert resolve_team("Argentina", roster) == "Argentina"
    assert resolve_team("argentina", roster) == "Argentina"
    assert resolve_team("USA", roster) == "United States"
    assert resolve_team("Nowhere", roster) is None


# --- parse_market end to end ---

def test_parse_market_builds_spec():
    matchup = Matchup("Argentina", "Colombia", neutral=True)
    pm = parse_market({"ticker": "T4", "series_ticker": "KXWCTOTAL",
                       "yes_sub_title": "Over 2.5 goals scored"}, matchup)
    assert pm.ticker == "T4"
    assert pm.contract == ContractSpec("over", 2.5)
    assert "Over 2.5" in pm.label


def test_parse_market_unmapped_returns_none():
    matchup = Matchup("France", "Brazil", neutral=True)
    assert parse_market({"ticker": "S", "series_ticker": "KXWCSPREAD",
                         "yes_sub_title": "France wins by more than 1.5 goals"}, matchup) is None
