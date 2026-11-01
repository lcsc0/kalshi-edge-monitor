"""Paper-only in-play run against live games. Places NO orders (GET requests only).

    python scripts/live_paper.py [--interval 4] [--minutes 120] [--db data/live_paper.sqlite]
    python scripts/live_paper.py --report [--db data/live_paper.sqlite]

Needs data/clubs.sqlite (scripts/build_club_db.py). Each tick: ESPN live scores for the
leagues Kalshi lists, Kalshi quotes for every live game, paper trades + arb scan.
"""
import argparse
import os
import sys
import time
from datetime import datetime, timezone

import httpx

from kalshi_edge.config import KALSHI_BASE_URL
from kalshi_edge.data.cache import connect as cache_connect
from kalshi_edge.kalshi.client import KalshiClient
from kalshi_edge.live import espn, ledger
from kalshi_edge.live.monitor import Config, Monitor
from kalshi_edge.live.report import report
from kalshi_edge.live.throttle import ThrottledHTTP
from kalshi_edge.model.mle_model import MLEGoalModel


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--interval", type=float, default=4.0, help="seconds between ticks")
    p.add_argument("--minutes", type=float, default=120.0, help="stop after this long")
    p.add_argument("--db", default="data/live_paper.sqlite")
    p.add_argument("--report", action="store_true")
    p.add_argument("--min-edge", type=float, default=Config.min_edge)
    args = p.parse_args(argv)

    conn = ledger.connect(args.db)
    if args.report:
        print(report(conn))
        return 0
    if not os.path.exists("data/clubs.sqlite"):
        print("data/clubs.sqlite missing — run scripts/build_club_db.py first.")
        return 1
    now = datetime.now(timezone.utc)
    model = MLEGoalModel.from_db(cache_connect("data/clubs.sqlite"), ref_date=now.date().isoformat(),
                                 since="2019-07-01", min_games=10)
    client = KalshiClient(http=ThrottledHTTP(base_url=KALSHI_BASE_URL, timeout=10.0))
    mon = Monitor(model, client, conn, Config(min_edge=args.min_edge),
                  log=lambda s: print(datetime.now(timezone.utc).strftime("%H:%M:%S"), s, flush=True))
    web = httpx.Client(timeout=10.0)
    end = time.time() + args.minutes * 60
    last_full = 0.0
    idle_since = None
    live_slugs: set[str] = set(espn.ESPN_LEAGUES)
    print(f"Paper-only in-play run. db={args.db} interval={args.interval}s. No orders are ever placed.", flush=True)
    while time.time() < end:
        t0 = time.time()
        slugs = set(espn.ESPN_LEAGUES) if t0 - last_full > 60 else live_slugs
        games = []
        for slug in slugs:
            try:
                games += espn.fetch_league(slug, web)
            except Exception as e:  # noqa: BLE001
                mon.log(f"[warn] espn {slug}: {type(e).__name__}")
        if t0 - last_full > 60:
            last_full = t0
            live_slugs = {g.slug for g in games if g.state == "in"} or set()
        active = [g for g in games if g.state == "in" or (g.state == "post" and g.game_id in mon.tracked
                                                          and not mon.tracked[g.game_id].get("skip"))]
        idle_since = None if active else (idle_since or t0)
        if idle_since and t0 - idle_since > 600:
            mon.log("no live games for 10 minutes; stopping")
            break
        mon.tick(active, datetime.now(timezone.utc).isoformat())
        time.sleep(max(0.0, args.interval - (time.time() - t0)))
    print(report(conn))
    return 0


if __name__ == "__main__":
    sys.exit(main())
