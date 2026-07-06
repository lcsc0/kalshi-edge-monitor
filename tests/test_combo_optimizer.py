from kalshi_edge.model.poisson import score_matrix
from kalshi_edge.pricer.pricer import Pricer
from kalshi_edge.combo.optimizer import ComboLeg, Combo, optimize, safety_shift, joint_prob


def _pricer(lam, mu, home="H", away="A"):
    return Pricer(score_matrix(lam, mu, rho=0.0, max_goals=10), home, away)


def _leg(game_id, pricer, leg, market_price):
    model_fair = pricer.same_game_combo([leg])
    return ComboLeg(game_id=game_id, pricer=pricer, leg=leg,
                    model_fair=model_fair, market_price=market_price,
                    edge=model_fair - market_price)


def test_optimize_picks_max_multiplier_meeting_target():
    pa = _pricer(2.0, 0.5, "Strong", "WeakA")   # strong home ~0.8
    pb = _pricer(1.6, 1.1, "Mid", "WeakB")       # home ~0.5
    la = _leg("A", pa, ("home",), market_price=0.70)
    lb = _leg("B", pb, ("home",), market_price=0.45)
    best = optimize([la, lb], target_prob=0.35, max_legs=4)
    assert isinstance(best, Combo)
    assert len(best.legs) == 2           # two-leg combo has the highest multiplier
    assert best.joint_prob >= 0.35
    # multiplier is the product of decimal odds
    assert abs(best.multiplier - (1 / 0.70) * (1 / 0.45)) < 1e-9


def test_optimize_rejects_combos_below_target():
    pa = _pricer(2.0, 0.5, "Strong", "WeakA")
    pb = _pricer(1.6, 1.1, "Mid", "WeakB")
    la = _leg("A", pa, ("home",), market_price=0.70)
    lb = _leg("B", pb, ("home",), market_price=0.45)
    best = optimize([la, lb], target_prob=0.60, max_legs=4)
    # two-leg joint ~0.4 < 0.60 infeasible; only game A single leg clears 0.60
    assert len(best.legs) == 1
    assert best.legs[0].game_id == "A"


def test_same_game_combo_is_not_marginal_product():
    pa = _pricer(2.0, 0.6, "Strong", "WeakA")
    home = _leg("A", pa, ("home",), market_price=0.70)
    over = _leg("A", pa, ("over", 1.5), market_price=0.60)
    jp = joint_prob([home, over])
    product = home.model_fair * over.model_fair
    assert abs(jp - pa.same_game_combo([("home",), ("over", 1.5)])) < 1e-12
    assert abs(jp - product) > 1e-4       # correlation priced, not multiplied


def test_leg_with_nonpositive_edge_is_refused():
    pa = _pricer(2.0, 0.5, "Strong", "WeakA")
    # market_price above model_fair -> edge <= 0
    la = _leg("A", pa, ("home",), market_price=0.99)
    assert optimize([la], target_prob=0.1, max_legs=4) is None


def test_safety_shift_prefers_safer_totals_bucket():
    # expected total ~2.5 -> under 2.5 sits on a high-variance boundary
    p = _pricer(1.3, 1.2)
    shifted = safety_shift(("under", 2.5), p, window=1.0, step=1.0)
    assert shifted == ("under", 3.5)
    # the safer bucket has the higher (safer) model probability
    assert p.price("under", 3.5) > p.price("under", 2.5)


def test_safety_shift_leaves_far_line_untouched():
    p = _pricer(1.3, 1.2)   # expected total ~2.5
    assert safety_shift(("under", 0.5), p, window=1.0, step=1.0) == ("under", 0.5)
    assert safety_shift(("home",), p) == ("home",)


def test_max_legs_bounds_the_search():
    pricers = [_pricer(1.8, 0.6, f"H{i}", f"A{i}") for i in range(5)]
    legs = [_leg(str(i), pricers[i], ("home",), market_price=0.55) for i in range(5)]
    best = optimize(legs, target_prob=0.0, max_legs=2)
    assert len(best.legs) <= 2
