from datetime import datetime, timedelta, timezone

from kalshi_edge.model.poisson import score_matrix
from kalshi_edge.pricer.pricer import Pricer
from kalshi_edge.kalshi.models import Orderbook, OrderbookLevel
from kalshi_edge.edge.engine import EdgeEngine
from scripts.recommend import build_report_data, build_report

NOW = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)


def _book(yes_top, no_top, depth=1000):
    return Orderbook(
        ticker="MKT",
        yes=(OrderbookLevel(price=yes_top, count=depth),),
        no=(OrderbookLevel(price=no_top, count=depth),))


def _game():
    p = Pricer(score_matrix(2.0, 0.6), "Strong", "Weak")
    analysis = {
        "home": "Strong", "away": "Weak",
        "expected_goals": {"home": 2.0, "away": 0.6},
        "strength": {"Strong": {"attack": 1.4, "defense": 0.8},
                     "Weak": {"attack": 0.7, "defense": 1.3}},
        "outcome_probs": p.moneyline(),
    }
    fresh = NOW - timedelta(seconds=30)
    home_fair = p.price("home")
    # price the market a touch below model fair so there's a positive edge
    yes_top = home_fair - 0.06
    return {
        "home": "Strong", "away": "Weak", "pricer": p, "analysis": analysis,
        "markets": [{
            "ticker": "KXWCGAME-STRONG", "contract": "home", "line": None,
            "label": "Strong to win", "orderbook": _book(yes_top, 1 - yes_top),
            "fetched_at": fresh,
        }],
    }


def test_build_report_data_produces_signal_and_report():
    data = build_report_data(
        [_game()], engine=EdgeEngine(), now=NOW, bankroll=1000,
        target_prob=0.4, date="2026-07-06", per_day_cap=200, include_combos=True)
    assert data["games"][0]["home"] == "Strong"
    assert len(data["signals"]) == 1
    assert not data["signals"][0].suppressed
    # a feasible single-leg combo was found and sized
    assert len(data["combos"]) == 1
    assert data["combos"][0]["stake"] > 0

    out = build_report(
        [_game()], engine=EdgeEngine(), now=NOW, bankroll=1000,
        target_prob=0.4, date="2026-07-06", per_day_cap=200, include_combos=True)
    assert "UNVALIDATED MODEL" in out
    assert "Strong to win" in out


def test_singles_only_by_default_and_heavy_favourite_vetoed():
    from kalshi_edge.edge.policy import DEFAULT_POLICY
    p = Pricer(score_matrix(3.6, 0.3), "Giant", "Minnow")
    fair = p.price("home")
    assert fair > DEFAULT_POLICY.max_side_prob          # genuinely a heavy favourite
    yes_top = fair - 0.05                               # 5pp "edge" the policy must distrust
    g = {"home": "Giant", "away": "Minnow", "pricer": p,
         "analysis": {"home": "Giant", "away": "Minnow"},
         "markets": [{"ticker": "T-GIANT", "contract": "home", "line": None, "label": "Giant",
                      "orderbook": _book(yes_top, 1 - yes_top),
                      "fetched_at": NOW - timedelta(seconds=30)}]}
    data = build_report_data([g], engine=EdgeEngine.from_policy(DEFAULT_POLICY), now=NOW,
                             bankroll=1000, date="2026-07-06")
    assert data["combos"] == []                          # no combos unless explicitly enabled
    assert data["signals"] == []                         # vetoed by max_side_prob


def test_single_stake_respects_per_bet_cap():
    from kalshi_edge.edge.policy import DEFAULT_POLICY
    p = Pricer(score_matrix(1.4, 1.1), "A", "B")   # balanced match -> moneyline mid-range
    fair = p.price("home")
    yes_top = fair - 0.05
    g = {"home": "A", "away": "B", "pricer": p,
         "analysis": {"home": "A", "away": "B"},
         "markets": [{"ticker": "T-HOME", "contract": "home", "line": None, "label": "A",
                      "orderbook": _book(yes_top, 1 - yes_top),
                      "fetched_at": NOW - timedelta(seconds=30)}]}
    data = build_report_data([g], engine=EdgeEngine.from_policy(DEFAULT_POLICY), now=NOW,
                             bankroll=1000, date="2026-07-06")
    assert data["combos"] == []
    assert len(data["signals"]) == 1
    stake = data["stakes"]["T-HOME"]
    assert 0 < stake <= 1000 * DEFAULT_POLICY.max_stake_fraction + 1e-9
    assert "stake $" in build_report([g], engine=EdgeEngine.from_policy(DEFAULT_POLICY),
                                     now=NOW, bankroll=1000, date="2026-07-06")
