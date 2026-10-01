"""Build data/clubs.sqlite from football-data.co.uk (top European club leagues).

Usage: python scripts/build_club_db.py [--first 2019] [--last 2025]
"""
import argparse
import os

import httpx

from kalshi_edge.data.cache import connect
from kalshi_edge.data.club_results import BASE_URL, LEAGUES, load_club_csv, season_codes

DB_PATH = "data/clubs.sqlite"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--first", type=int, default=2019, help="first season start year")
    p.add_argument("--last", type=int, default=2026, help="last season start year")
    p.add_argument("--db", default=DB_PATH)
    args = p.parse_args()
    os.makedirs(os.path.dirname(args.db) or ".", exist_ok=True)
    if os.path.exists(args.db):
        os.remove(args.db)  # rebuild from scratch: avoids duplicate rows
    conn = connect(args.db)
    total = 0
    for season in season_codes(args.first, args.last):
        for div in LEAGUES:
            resp = httpx.get(BASE_URL.format(season=season, div=div), timeout=30,
                             follow_redirects=True)
            if resp.status_code != 200:
                print(f"  skip {div} {season}: HTTP {resp.status_code}")
                continue
            n = load_club_csv(conn, resp.content.decode("utf-8-sig", "replace"), div)
            total += n
        print(f"season {season}: running total {total}")
    print(f"Loaded {total} club matches into {args.db}")


if __name__ == "__main__":
    main()
