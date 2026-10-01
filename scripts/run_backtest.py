import sys
from kalshi_edge.data.cache import connect
from kalshi_edge.backtest.runner import backtest_outcomes
from kalshi_edge.backtest.metrics import (
    brier_score, log_loss, accuracy, baseline_brier, calibration_table,
)

DB = "data/football.sqlite"


def main() -> None:
    start = sys.argv[1] if len(sys.argv) > 1 else "2022-01-01"
    end = sys.argv[2] if len(sys.argv) > 2 else "2024-12-31"
    recs = backtest_outcomes(connect(DB), test_start=start, test_end=end, since="2014-01-01")
    print(f"Backtest {start}..{end}: {len(recs)} matches")
    print(f"  Brier        : {brier_score(recs):.4f}  (baseline {baseline_brier(recs):.4f})")
    print(f"  Log-loss     : {log_loss(recs):.4f}")
    print(f"  Accuracy     : {accuracy(recs):.3f}")
    print("  Calibration (home-win prob):")
    for row in calibration_table(recs, outcome="home", bins=10):
        lo, hi = row["bin"]
        print(f"    {lo:.1f}-{hi:.1f}  n={row['n']:<5} pred={row['avg_pred']:.3f} "
              f"observed={row['observed']:.3f}")


if __name__ == "__main__":
    main()
