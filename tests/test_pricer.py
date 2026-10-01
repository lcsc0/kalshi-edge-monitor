from kalshi_edge.data.cache import connect
from kalshi_edge.data.intl_results import load_results_csv
from kalshi_edge.model.goal_model import GoalModel
from kalshi_edge.pricer.pricer import Pricer
from kalshi_edge.pricer import contracts

ROWS = "date,home_team,away_team,home_score,away_score,tournament,city,country,neutral\n" + "".join(
    f"2025-0{i%9+1}-01,Strong,Weak,3,0,Friendly,X,Y,TRUE\n"
    f"2025-0{i%9+1}-15,Weak,Strong,0,3,Friendly,X,Y,TRUE\n" for i in range(10))


def _model():
    conn = connect(); load_results_csv(conn, ROWS)
    return GoalModel.from_db(conn, ref_date="2025-10-01")


def _pricer(home="Strong", away="Weak"):
    return Pricer.from_model(_model(), home, away, neutral=True)


def test_moneyline_matches_model_outcome_probs():
    m = _model()
    p = _pricer()
    ml = p.moneyline()
    ref = m.match_probabilities("Strong", "Weak", neutral=True)
    assert abs(ml["home"] - ref["home"]) < 1e-9
    assert abs(ml["draw"] - ref["draw"]) < 1e-9
    assert abs(ml["away"] - ref["away"]) < 1e-9
    assert round(sum(ml.values()), 6) == 1.0


def test_totals_complementary_and_named_helpers():
    p = _pricer()
    assert round(p.total_over(2.5) + p.total_under(2.5), 6) == 1.0
    assert 0.0 <= p.both_teams_score() <= 1.0


def test_price_named_dispatch_matches_methods():
    p = _pricer()
    assert abs(p.price("over", line=2.5) - p.total_over(2.5)) < 1e-12
    assert abs(p.price("home") - p.moneyline()["home"]) < 1e-12
    assert abs(p.price("btts") - p.both_teams_score()) < 1e-12


def test_same_game_combo_is_intersection_not_product():
    # Strong to win AND over 2.5 in the SAME game: must be the joint sum,
    # which equals the direct predicate intersection over the shared matrix.
    p = _pricer()
    combo = p.same_game_combo([("home",), ("over", 2.5)])
    direct = contracts.price_predicate(
        p.matrix, lambda x, y: contracts.home_win(x, y) and contracts.over(2.5)(x, y))
    assert abs(combo - direct) < 1e-12
    # And it is NOT the product of the two marginals (correlation matters).
    product = p.price("home") * p.total_over(2.5)
    assert abs(combo - product) > 1e-6


def test_cross_game_combo_multiplies_independent_pricers():
    p1 = _pricer("Strong", "Weak")
    p2 = _pricer("Strong", "Weak")
    joint = Pricer.combo_across_games([
        (p1, [("home",)]),
        (p2, [("over", 2.5)]),
    ])
    expected = p1.price("home") * p2.total_over(2.5)
    assert abs(joint - expected) < 1e-12
