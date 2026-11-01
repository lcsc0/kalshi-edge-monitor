"""Summarise a paper in-play run: trades, arbs, and goal-reaction lag."""
from collections import defaultdict


def _fmt(x, nd=2):
    return "n/a" if x is None else f"{x:+.{nd}f}"


def goal_lags(conn, window_s: float = 90.0, min_move: float = 0.05):
    """For each score change, when did Kalshi's moneyline reprice relative to when the score
    feed showed it? Negative lag = Kalshi moved BEFORE the feed (we were late)."""
    out = []
    prev = {}
    for r in conn.execute("SELECT * FROM game_ticks ORDER BY ts").fetchall():
        last = prev.get(r["game_id"])
        prev[r["game_id"]] = (r["hs"], r["as_"])
        if last is None or last == (r["hs"], r["as_"]):
            continue
        t0 = r["ts"]
        series = defaultdict(list)
        for q in conn.execute(
                "SELECT ts, ticker, yes_bid, yes_ask FROM quotes WHERE game_id=? AND ts BETWEEN ? AND ? "
                "AND ticker LIKE '%GAME-%' ORDER BY ts", (r["game_id"], t0 - window_s, t0 + window_s)):
            if q["yes_bid"] is not None and q["yes_ask"] is not None:
                series[q["ticker"]].append((q["ts"], (q["yes_bid"] + q["yes_ask"]) / 2))
        best = max(((max(m for _, m in v) - min(m for _, m in v), k) for k, v in series.items() if len(v) > 3),
                   default=(0, None))
        if best[1] is None or best[0] < min_move:
            out.append({"game": f"{r['home']} v {r['away']}", "score": f"{r['hs']}-{r['as_']}",
                        "minute": r["minute"], "lag": None, "move": best[0]})
            continue
        v = series[best[1]]
        start, end = v[0][1], v[-1][1]
        half = next((t for t, m in v if abs(m - start) >= abs(end - start) / 2), None)
        out.append({"game": f"{r['home']} v {r['away']}", "score": f"{r['hs']}-{r['as_']}",
                    "minute": r["minute"], "lag": None if half is None else half - t0, "move": abs(end - start)})
    return out


def report(conn) -> str:
    L = ["", "=== PAPER IN-PLAY REPORT (no orders were placed) ==="]
    n_ticks = conn.execute("SELECT COUNT(*), COUNT(DISTINCT game_id) FROM game_ticks").fetchone()
    L.append(f"ticks logged: {n_ticks[0]} across {n_ticks[1]} games")

    L.append("\n-- paper trades (settled only; fee included) --")
    rows = conn.execute("SELECT * FROM paper_trades").fetchall()
    open_n = sum(1 for r in rows if r["result_yes"] is None)
    L.append(f"{len(rows)} trades, {open_n} still unsettled")
    by = defaultdict(list)
    for r in rows:
        if r["result_yes"] is not None:
            by[r["kind"]].append(r)
            by["ALL"].append(r)
    for kind in ("latency", "model", "ALL"):
        rs = by.get(kind, [])
        if not rs:
            continue
        stake = sum(r["size"] * r["entry"] for r in rs)
        pnl = sum(r["pnl"] for r in rs)
        d = [r for r in rs if r["pnl_delayed"] is not None]
        pnl_d = sum(r["pnl_delayed"] for r in d)
        stake_d = sum(r["size"] * r["entry_delayed"] for r in d)
        wins = sum(1 for r in rs if r["pnl"] > 0)
        L.append(f"  {kind:8s} n={len(rs):3d} win%={100*wins/len(rs):4.0f} "
                 f"avg_edge_claimed={sum(r['edge_net'] for r in rs)/len(rs):+.3f}  "
                 f"P&L instant-fill ${pnl:+.2f} (ROI {_fmt(100*pnl/stake if stake else None,1)}%)  "
                 f"1-tick-late fill ${pnl_d:+.2f} on {len(d)} (ROI {_fmt(100*pnl_d/stake_d if stake_d else None,1)}%)")
    L.append("  (instant-fill assumes you hit the ask you saw; 1-tick-late uses the ask one poll later)")

    L.append("\n-- structural arbitrage found (net of fees, at displayed size) --")
    arbs = conn.execute("SELECT kind, COUNT(*) n, SUM(net) net, MAX(net) mx FROM arbs GROUP BY kind").fetchall()
    if not arbs:
        L.append("  none")
    for a in arbs:
        L.append(f"  {a['kind']}: {a['n']} sightings, best ${a['mx']:.2f}, sum-of-sightings ${a['net']:.2f} "
                 f"(sightings repeat across ticks - not additive profit)")

    L.append("\n-- goal reaction: Kalshi reprice time minus score-feed time (negative = Kalshi first) --")
    lags = goal_lags(conn)
    if not lags:
        L.append("  no goals observed")
    for g in lags:
        L.append(f"  {g['game']} {g['score']} @{g['minute']:.0f}'  move {g['move']:.2f}  lag {_fmt(g['lag'],1)}s")
    ok = [g["lag"] for g in lags if g["lag"] is not None]
    if ok:
        L.append(f"  median lag {sorted(ok)[len(ok)//2]:+.1f}s over {len(ok)} goals")
    return "\n".join(L)
