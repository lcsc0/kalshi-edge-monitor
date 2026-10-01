"""Log every open club-soccer market (model vs market) to the shadow signal DB.

    python scripts/shadow_club.py    # needs data/clubs.sqlite (scripts/build_club_db.py)

Writes to $SIGNALS_DB (default data/football.sqlite). Settle later with
scripts/settle_signals.py. Read-only against Kalshi; places no orders.
"""
import os
import sys
from datetime import datetime, timezone

import httpx

from kalshi_edge.config import KALSHI_BASE_URL
from kalshi_edge.data.cache import connect
from kalshi_edge.data.club_results import FIXTURES_URL, load_fixtures_csv
from kalshi_edge.edge.blend import BlendTable
from kalshi_edge.edge.club_shadow import build_club_signals
from kalshi_edge.edge.engine import EdgeEngine
from kalshi_edge.edge.policy import DEFAULT_POLICY
from kalshi_edge.edge.signal_log import ensure_table, log_signal
from kalshi_edge.kalshi.client import KalshiClient
from kalshi_edge.kalshi.http import KalshiHTTP
from kalshi_edge.model.mle_model import MLEGoalModel

CLUB_DB = "data/clubs.sqlite"


def main() -> int:
    now = datetime.now(timezone.utc)
    if not os.path.exists(CLUB_DB):
        print(f"{CLUB_DB} missing — run scripts/build_club_db.py first.")
        return 1
    clubs = connect(CLUB_DB)
    model = MLEGoalModel.from_db(clubs, ref_date=now.date().isoformat(),
                                 since="2019-07-01", min_games=10)
    fix = connect(":memory:")
    resp = httpx.get(FIXTURES_URL, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    print(f"Loaded {load_fixtures_csv(fix, resp.content.decode('utf-8-sig', 'replace'))} fixtures")

    sconn = connect(os.environ.get("SIGNALS_DB") or "data/football.sqlite")
    ensure_table(sconn)
    blend = BlendTable.from_db(sconn)
    client = KalshiClient(http=KalshiHTTP(base_url=KALSHI_BASE_URL, timeout=20.0, max_retries=4))
    engine = EdgeEngine.from_policy(DEFAULT_POLICY)
    signals, stats = build_club_signals(client, model, fix, engine, now=now, blend=blend,
                                        intended_size=DEFAULT_POLICY.intended_size)
    logged = 0
    for sig in signals:
        if sig.market_implied > 0:
            log_signal(sconn, sig, fetched_at=now.isoformat())
            logged += 1
    bets = sum(1 for s in signals if not s.suppressed)
    print(f"Logged {logged} markets ({bets} would-be bets after blend + guardrails). Stats: {stats}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
