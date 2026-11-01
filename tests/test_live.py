from kalshi_edge.live.espn import parse_minute
from kalshi_edge.live.inplay import inplay_matrix, kalshi_fee, remaining_share
from kalshi_edge.pricer.pricer import Pricer


def test_parse_minute():
    assert parse_minute("34'") == 34
    assert parse_minute("45'+3'") == 48
    assert parse_minute("90'+7'") == 97


def test_remaining_share_monotone_and_bounds():
    assert remaining_share(1, 0, "STATUS_FIRST_HALF") == 1.0
    assert abs(remaining_share(1, 45, "STATUS_HALFTIME") - 0.54) < 1e-9
    assert remaining_share(2, 46, "STATUS_SECOND_HALF") > remaining_share(2, 80, "STATUS_SECOND_HALF") > 0
    assert 0 < remaining_share(2, 97, "STATUS_SECOND_HALF") < 0.02


def test_inplay_matrix_is_conditioned_on_score():
    m = inplay_matrix(1.5, 1.1, 2, 0, remaining_share(2, 80, "STATUS_SECOND_HALF"))
    assert abs(sum(map(sum, m)) - 1) < 1e-9
    p = Pricer(m)
    assert p.price("home") > 0.95            # 2-0 up with ~10 min left
    assert abs(p.price("over", 1.5) - 1) < 1e-9  # already 2 goals
    assert p.price("btts") < 0.2


def test_fee_rounds_up_to_cent():
    assert kalshi_fee(0.5, 100) == 1.75
    assert kalshi_fee(0.99, 1) == 0.01
