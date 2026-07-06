import pytest

from kalshi_edge.edge.devig import devig, devig_single


def test_devig_normalizes_overround_partition():
    # home/draw/away priced with overround: sum = 1.20
    fair = devig({"home": 0.50, "draw": 0.30, "away": 0.40})
    assert round(sum(fair.values()), 9) == 1.0
    # proportions preserved; home still the largest
    assert fair["home"] > fair["away"] > fair["draw"]
    assert abs(fair["home"] - 0.50 / 1.20) < 1e-12


def test_devig_leaves_fair_partition_unchanged():
    fair = devig({"yes": 0.6, "no": 0.4})
    assert abs(fair["yes"] - 0.6) < 1e-12
    assert abs(fair["no"] - 0.4) < 1e-12


def test_devig_single_returns_mid():
    assert devig_single(0.62) == 0.62


def test_devig_rejects_nonpositive_sum():
    with pytest.raises(ValueError):
        devig({})
    with pytest.raises(ValueError):
        devig({"a": 0.0, "b": 0.0})
