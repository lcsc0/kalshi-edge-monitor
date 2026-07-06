from kalshi_edge.edge.engine import EdgeSignal
from kalshi_edge.combo.optimizer import ComboLeg, Combo
from kalshi_edge.model.poisson import score_matrix
from kalshi_edge.pricer.pricer import Pricer
from kalshi_edge.report.report import render_report, BANNER


ANALYSIS = {
    "home": "Strong", "away": "Weak", "neutral": True,
    "expected_goals": {"home": 2.10, "away": 0.70},
    "strength": {"Strong": {"attack": 1.40, "defense": 0.80},
                 "Weak": {"attack": 0.70, "defense": 1.30}},
    "outcome_probs": {"home": 0.72, "draw": 0.18, "away": 0.10},
}


def _signal():
    return EdgeSignal(
        ticker="KXWCGAME-STRONG", side="yes", model_fair=0.72,
        market_implied=0.64, edge=0.08, fillable_size=100, slippage=0.0,
        suppressed=False, suppression_reason=None, analysis=ANALYSIS)


def _combo():
    p = Pricer(score_matrix(2.0, 0.6), "Strong", "Weak")
    leg = ComboLeg(game_id="A", pricer=p, leg=("home",),
                   model_fair=0.72, market_price=0.64, edge=0.08)
    return Combo(legs=[leg], joint_prob=0.72, multiplier=1 / 0.64)


def _data(validated=False):
    return {
        "date": "2026-07-06",
        "validated": validated,
        "games": [{
            "home": "Strong", "away": "Weak",
            "markets": [
                {"contract": "home", "model_fair": 0.72,
                 "market_implied": 0.64, "edge": 0.08},
                {"contract": "over 2.5", "model_fair": 0.55,
                 "market_implied": 0.58, "edge": -0.03},
            ],
        }],
        "signals": [_signal()],
        "combos": [{"combo": _combo(), "stake": 50.0, "fraction": 0.25}],
    }


def test_report_shows_persistent_banner_until_validated():
    out = render_report(_data(validated=False))
    assert out.lstrip().startswith(BANNER) or BANNER in out.splitlines()[0:3][0] \
        or BANNER in "\n".join(out.splitlines()[:3])
    assert BANNER in out


def test_report_hides_banner_when_validated():
    out = render_report(_data(validated=True))
    assert BANNER not in out


def test_report_shows_per_market_fair_vs_kalshi_with_edge():
    out = render_report(_data())
    assert "Strong" in out and "Weak" in out
    assert "0.72" in out and "0.64" in out       # model fair vs market
    assert "home" in out


def test_report_includes_analysis_drivers_not_bare_edge():
    out = render_report(_data())
    # §3a: the lineup/form/strength drivers must appear with the flagged signal
    assert "Expected goals" in out
    assert "2.10" in out and "0.70" in out        # expected goals numbers
    assert "attack" in out                        # strength drivers
    assert "0.72" in out                          # outcome prob shown


def test_report_shows_combo_with_fractional_kelly_sizing():
    out = render_report(_data())
    assert "Combo" in out or "combo" in out
    assert "$50.00" in out or "50.00" in out
    assert "Kelly" in out
