from kalshi_edge.edge.sizing import kelly_fraction, fractional_kelly, size_bet


def test_kelly_fraction_binary_formula():
    # buy YES at cost 0.50, pays $1; p=0.60 => (0.60-0.50)/(1-0.50) = 0.20
    assert abs(kelly_fraction(0.60, 0.50) - 0.20) < 1e-12


def test_negative_edge_clamps_to_zero():
    assert kelly_fraction(0.40, 0.50) == 0.0
    assert fractional_kelly(0.40, 0.50) == 0.0


def test_fractional_is_a_quarter_and_less_than_full():
    full = kelly_fraction(0.60, 0.50)
    frac = fractional_kelly(0.60, 0.50, fraction=0.25)
    assert abs(frac - 0.25 * full) < 1e-12
    assert frac < full


def test_size_bet_applies_fraction_to_bankroll():
    # frac kelly = 0.25 * 0.20 = 0.05 of a 1000 bankroll = 50
    stake = size_bet(0.60, 0.50, bankroll=1000, fraction=0.25)
    assert abs(stake - 50.0) < 1e-9


def test_size_bet_floored_by_tightest_cap():
    # unconstrained stake would be 50; per-game remaining is 30 -> floored to 30
    stake = size_bet(0.60, 0.50, bankroll=1000, fraction=0.25,
                     per_combo_cap=100, per_game_cap=80, game_exposure=50,
                     per_day_cap=500, day_exposure=100)
    assert abs(stake - 30.0) < 1e-9


def test_exhausted_daily_budget_yields_zero():
    stake = size_bet(0.60, 0.50, bankroll=1000, fraction=0.25,
                     per_day_cap=100, day_exposure=100)
    assert stake == 0.0
