from kalshi_edge.data.cache import connect
from kalshi_edge.data.sources import download_text
from kalshi_edge.data.intl_results import (
    RESULTS_URL, GOALS_URL, load_results_csv, load_goalscorers_csv,
)

DB_PATH = "data/football.sqlite"


def main() -> None:
    import os
    os.makedirs("data", exist_ok=True)
    conn = connect(DB_PATH)
    r = load_results_csv(conn, download_text(RESULTS_URL))
    g = load_goalscorers_csv(conn, download_text(GOALS_URL))
    print(f"Loaded {r} matches and {g} goals into {DB_PATH}")


if __name__ == "__main__":
    main()
