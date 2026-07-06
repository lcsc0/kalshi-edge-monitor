from kalshi_edge.backtest.metrics import (
    brier_score, log_loss, accuracy, baseline_brier, calibration_table,
)

PERFECT = [{"date": "d", "probs": {"home": 1.0, "draw": 0.0, "away": 0.0}, "outcome": "home"}]
RECORDS = [
    {"date": "d", "probs": {"home": 0.6, "draw": 0.3, "away": 0.1}, "outcome": "home"},
    {"date": "d", "probs": {"home": 0.2, "draw": 0.3, "away": 0.5}, "outcome": "away"},
    {"date": "d", "probs": {"home": 0.3, "draw": 0.4, "away": 0.3}, "outcome": "draw"},
]


def test_brier_zero_for_perfect_prediction():
    assert brier_score(PERFECT) == 0.0


def test_brier_and_logloss_positive_for_imperfect():
    assert brier_score(RECORDS) > 0.0
    assert log_loss(RECORDS) > 0.0


def test_accuracy_counts_argmax_hits():
    assert accuracy(RECORDS) == 1.0


def test_model_beats_baseline_when_it_has_signal():
    assert brier_score(RECORDS) < baseline_brier(RECORDS)


def test_calibration_table_bins_and_reports_frequency():
    recs = [{"date": "d", "probs": {"home": 0.85, "draw": 0.1, "away": 0.05},
             "outcome": "home" if i < 8 else "away"} for i in range(10)]
    table = calibration_table(recs, outcome="home", bins=10)
    top = [row for row in table if row["bin"][0] <= 0.85 < row["bin"][1] or row["bin"][1] == 1.0][-1]
    assert top["n"] == 10 and round(top["observed"], 2) == 0.80
