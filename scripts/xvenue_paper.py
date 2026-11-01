"""Paper-only cross-venue (Kalshi <-> Polymarket) arbitrage scan on live soccer games.

    python scripts/xvenue_paper.py [--interval 3] [--minutes 100] [--db data/xvenue_paper.sqlite]
    python scripts/xvenue_paper.py --report

Every tick, per live game, compares the home/draw/away YES books on both venues and logs
a locked-profit opportunity when  YES(one venue) + NO(other venue) costs < $1 after both
venues' taker fees. It records how long each opportunity persisted (your real constraint:
the gap must outlive your polling + order latency). GET/POST-books only; no orders.
"""
import argparse
import os
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, date

import httpx

from kalshi_edge.config import KALSHI_BASE_URL
from kalshi_edge.data.cache import connect as cache_connect
from kalshi_edge.kalshi.client import KalshiClient
from kalshi_edge.live import espn
from kalshi_edge.live.inplay import kalshi_fee
from kalshi_edge.live.monitor import Monitor, quote_of
from kalshi_edge.live.polymarket import find_match_event, poly_fee, top_of_book
from kalshi_edge.live.throttle import ThrottledHTTP
from kalshi_edge.model.mle_model import MLEGoalModel
from kalshi_edge.kalshi.market_parse import parse_contract

SCHEMA = """
CREATE TABLE IF NOT EXISTS xv (ts REAL, game TEXT, outcome TEXT, k_bid REAL, k_ask REAL, k_bsz REAL, k_asz REAL,
  p_bid REAL, p_ask REAL, p_bsz REAL, p_asz REAL, hs INT, as_ INT, minute REAL,
  net_buyK_sellP REAL, net_buyP_sellK REAL, size REAL);
"""
SIZE = 100.0


def edge_after_fees(buy_ask, sell_bid, buy_fee, sell_fee, n):
    """Buy YES at buy_ask on one venue, buy NO at (1-sell_bid) on the other. Locked $1 payout."""
    cost = buy_ask + (1 - sell_bid)
    return (1 - cost) - (buy_fee(buy_ask, n) + sell_fee(1 - sell_bid, n)) / n


def report(conn) -> str:
    L = ["", "=== CROSS-VENUE PAPER REPORT (Kalshi <-> Polymarket; no orders placed) ==="]
    r = conn.execute("SELECT COUNT(*), COUNT(DISTINCT game) FROM xv").fetchone()
    L.append(f"{r[0]} comparisons over {r[1]} games")
    rows = conn.execute("SELECT * FROM xv ORDER BY game, outcome, ts").fetchall()
    imm = dly = 0.0
    n_imm = n_dly = 0
    best_d = None
    seq = {}
    for x in rows:
        seq.setdefault((x["game"], x["outcome"]), []).append(x)
    for xs in seq.values():
        for cur, nxt in zip(xs, xs[1:]):
            n = min(cur["size"], 100.0)
            for net, buy_k in ((cur["net_buyK_sellP"], True), (cur["net_buyP_sellK"], False)):
                if net is None or net <= 0:
                    continue
                imm += net * n
                n_imm += 1
                # latency test: same trade, but filled at the prices one tick (~poll interval) later
                if buy_k and nxt["k_ask"] and nxt["p_bid"]:
                    d = edge_after_fees(nxt["k_ask"], nxt["p_bid"], kalshi_fee, poly_fee, n)
                elif not buy_k and nxt["p_ask"] and nxt["k_bid"]:
                    d = edge_after_fees(nxt["p_ask"], nxt["k_bid"], poly_fee, kalshi_fee, n)
                else:
                    d = None
                if d is not None and d > 0:
                    dly += d * n
                    n_dly += 1
                    best_d = d if best_d is None else max(best_d, d)
    L.append(f"ticks with a locked-profit gap (after assumed fees, top-of-book size, capped 100): {n_imm}, "
             f"paper profit if filled instantly ${imm:.2f}")
    L.append(f"...of those, still profitable one tick later: {n_dly}, paper profit ${dly:.2f}"
             f"{'' if best_d is None else f' (best {best_d:.3f}/contract)'}")
    L.append("  (ticks repeat the same opportunity - treat $ as an upper bound; sizes are top-of-book only)")
    cross = conn.execute("SELECT AVG(ABS(((k_bid+k_ask)/2)-((p_bid+p_ask)/2))) FROM xv WHERE k_bid IS NOT NULL AND p_bid IS NOT NULL AND k_ask IS NOT NULL AND p_ask IS NOT NULL").fetchone()[0]
    L.append(f"mean |Kalshi mid - Polymarket mid|: {cross if cross is None else round(cross, 4)}")
    return "\n".join(L)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--interval", type=float, default=3.0)
    p.add_argument("--minutes", type=float, default=100.0)
    p.add_argument("--db", default="data/xvenue_paper.sqlite")
    p.add_argument("--report", action="store_true")
    a = p.parse_args(argv)
    conn = sqlite3.connect(a.db)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    if a.report:
        print(report(conn))
        return 0
    now = datetime.now(timezone.utc)
    model = MLEGoalModel.from_db(cache_connect("data/clubs.sqlite"), ref_date=now.date().isoformat(),
                                 since="2019-07-01", min_games=10)
    kal = KalshiClient(http=ThrottledHTTP(base_url=KALSHI_BASE_URL, timeout=10.0))
    mon = Monitor(model, kal, sqlite3.connect(":memory:"), log=lambda s: print(datetime.now(timezone.utc).strftime("%H:%M:%S"), s, flush=True))
    web = httpx.Client(timeout=10.0)
    tracked: dict[str, dict | None] = {}
    end, idle = time.time() + a.minutes * 60, None
    print("Paper-only cross-venue scan. No orders are ever placed.", flush=True)
    while time.time() < end:
        t0 = time.time()
        games = []
        for slug in espn.ESPN_LEAGUES:
            try:
                games += [g for g in espn.fetch_league(slug, web) if g.state == "in"]
            except Exception as e:  # noqa: BLE001
                print("[warn] espn", slug, type(e).__name__, flush=True)
        idle = None if games else (idle or t0)
        if idle and t0 - idle > 600:
            print("no live games for 10 minutes; stopping", flush=True)
            break
        for g in games:
            info = tracked.get(g.game_id, "new")
            if info == "new":
                k = mon.discover(g, now.isoformat())
                if k is None or k is mon.__class__ and False:
                    tracked[g.game_id] = None
                    continue
                try:
                    pm = find_match_event(web, g.home, g.away, date.today())
                except Exception as e:  # noqa: BLE001
                    print("[warn] polymarket search", type(e).__name__, flush=True)
                    continue
                if pm is None:
                    print(f"[skip] {g.home} v {g.away}: no Polymarket moneyline event", flush=True)
                    tracked[g.game_id] = None
                    continue
                print(f"[xv] {g.home} v {g.away}: Kalshi {k['suffix']} <-> Polymarket {pm['slug']}", flush=True)
                tracked[g.game_id] = info = {"k": k, "pm": pm}
            if info is None:
                continue
            try:
                with ThreadPoolExecutor(2) as ex:   # fetch both venues at the same instant
                    fk = ex.submit(lambda: list(kal.iter_markets(
                        event_ticker=f"KX{info['k']['prefix']}GAME-{info['k']['suffix']}", status="open")))
                    fp = ex.submit(top_of_book, web, info["pm"]["tokens"])
                    ms, pb = fk.result(), fp.result()
            except Exception as e:  # noqa: BLE001
                print("[warn] fetch", type(e).__name__, flush=True)
                continue
            ts = time.time()
            for m in ms:
                spec = parse_contract(m["ticker"].split("-")[0], m.get("yes_sub_title") or "", info["k"]["home_k"], info["k"]["away_k"])
                if spec is None or spec.name not in pb:
                    continue
                kq, pq = quote_of(m), pb[spec.name]
                n = min(SIZE, kq["ask_sz"], pq["ask_sz"], kq["bid_sz"], pq["bid_sz"]) or SIZE
                kbuy = (edge_after_fees(kq["yes_ask"], pq["bid"], kalshi_fee, poly_fee, n)
                        if kq["yes_ask"] and pq["bid"] and kq["yes_ask"] < 1 else None)
                pbuy = (edge_after_fees(pq["ask"], kq["yes_bid"], poly_fee, kalshi_fee, n)
                        if pq["ask"] and kq["yes_bid"] and pq["ask"] < 1 else None)
                conn.execute("INSERT INTO xv VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                             (ts, f"{g.home} v {g.away}", spec.name, kq["yes_bid"], kq["yes_ask"], kq["bid_sz"], kq["ask_sz"],
                              pq["bid"], pq["ask"], pq["bid_sz"], pq["ask_sz"], g.home_score, g.away_score, g.minute,
                              kbuy, pbuy, n))
                best = max(v for v in (kbuy, pbuy, -9) if v is not None)
                if best > 0:
                    print(f"[XV ARB] {g.home} {g.home_score}-{g.away_score} {g.away} {spec.name}: net {best:+.3f}/contract "
                          f"K {kq['yes_bid']}/{kq['yes_ask']} P {pq['bid']}/{pq['ask']}", flush=True)
            conn.commit()
        time.sleep(max(0.0, a.interval - (time.time() - t0)))
    print(report(conn))
    return 0


if __name__ == "__main__":
    sys.exit(main())
