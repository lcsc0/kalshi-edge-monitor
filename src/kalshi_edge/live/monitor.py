"""Paper-only in-play monitor: ESPN live score + Kalshi quotes -> logged would-be trades.

Nothing here can place an order: it only issues GETs. Per tick and live game it
  1. records the score and the quotes (so goal-reaction lag can be measured offline),
  2. prices every GAME/TOTAL/BTTS market off the in-play model and logs a paper buy when
     the fee-adjusted edge clears a threshold - at the ask seen *now* (optimistic) and at
     the ask seen on the *next* tick (the latency-penalised fill),
  3. scans for structural arbitrage (moneyline YES asks summing < $1, crossed totals ladders).
Paper trades settle locally from the final score when ESPN reports the game finished.
"""
import json
import time
from datetime import date
from collections import defaultdict
from dataclasses import dataclass

from kalshi_edge.kalshi.club_match import event_date, name_score
from kalshi_edge.kalshi.market_parse import parse_contract
from kalshi_edge.live.espn import ESPN_LEAGUES, LiveGame
from kalshi_edge.live.inplay import inplay_matrix, kalshi_fee, remaining_share
from kalshi_edge.pricer.contracts import price_predicate
from kalshi_edge.pricer.pricer import Pricer, _predicate_for

KINDS = ("GAME", "TOTAL", "BTTS")
RETRY = object()


@dataclass
class Config:
    min_edge: float = 0.04        # net of fee, in dollars per contract
    max_edge: float = 0.30        # larger = probably bad data, not opportunity
    min_price: float = 0.03
    max_price: float = 0.97
    min_ask_size: float = 20.0
    max_size: float = 100.0       # paper contracts per trade
    max_minute: float = 88.0
    latency_window_s: float = 90.0  # a trade this soon after a goal is tagged "latency"
    model_band: tuple = (0.15, 0.85)    # P(side wins) band, same as edge.policy.DEFAULT_POLICY
    latency_band: tuple = (0.05, 0.95)  # wider: post-goal stale quotes sit on heavy favourites


def _px(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f


def quote_of(m: dict) -> dict:
    return {"yes_bid": _px(m.get("yes_bid_dollars")), "yes_ask": _px(m.get("yes_ask_dollars")),
            "bid_sz": _px(m.get("yes_bid_size_fp")) or 0.0, "ask_sz": _px(m.get("yes_ask_size_fp")) or 0.0}


class Monitor:
    def __init__(self, model, client, conn, cfg: Config | None = None, log=print):
        self.model, self.client, self.conn, self.cfg, self.log = model, client, conn, cfg or Config(), log
        self.tracked: dict[str, dict] = {}      # game_id -> {game, suffix, names..., score_seen_ts}
        self.traded: set = set()                 # (game_id, ticker, side, hs, as)
        self.pending: dict[tuple, int] = {}      # (ticker, side) -> trade id awaiting delayed fill
        self.api_errors = 0
        self.retry_after: dict[str, float] = {}

    # ---- matching -------------------------------------------------------------------
    def model_name(self, espn_name: str) -> str | None:
        best = max(self.model.fit.attack, key=lambda t: name_score(espn_name, t))
        return best if name_score(espn_name, best) >= 0.8 else None

    def discover(self, g: LiveGame, now: str) -> dict | None:
        """Find the Kalshi event for an ESPN game via the model's team names."""
        h, a = self.model_name(g.home), self.model_name(g.away)
        if not h or not a:
            self.log(f"[skip] {g.home} v {g.away}: team not in model")
            return None
        prefix = ESPN_LEAGUES[g.slug]
        try:
            ms = list(self.client.iter_markets(series_ticker=f"KX{prefix}GAME", status="open"))
        except Exception as e:  # noqa: BLE001
            self.api_errors += 1
            self.log(f"[warn] discovery failed {prefix}: {type(e).__name__} - will retry")
            return RETRY
        events = defaultdict(list)
        for m in ms:
            events[m["event_ticker"]].append(m)
        best = None
        for et, legs in events.items():
            names = [x["yes_sub_title"] for x in legs if x["yes_sub_title"].lower() not in ("tie", "draw")]
            if len(names) != 2:
                continue
            d = event_date(et)
            if d is None or abs((d - date.fromisoformat(now[:10])).days) > 1:
                continue
            for ka, kb, orient in ((names[0], names[1], 0), (names[1], names[0], 1)):
                s = min(name_score(ka, h), name_score(kb, a))
                if best is None or s > best[0]:
                    best = (s, et, ka, kb)
        if best is None or best[0] < 0.6:
            self.log(f"[skip] {g.home} v {g.away}: no Kalshi event matched")
            return None
        _, et, home_k, away_k = best
        suffix = et.split("-", 1)[1]
        self.log(f"[track] {g.home} v {g.away} -> {et} (model: {h} v {a})")
        return {"suffix": suffix, "prefix": prefix, "model_h": h, "model_a": a,
                "home_k": home_k, "away_k": away_k, "goal_ts": None, "score": None}

    # ---- one tick -------------------------------------------------------------------
    def tick(self, games: list[LiveGame], now_iso: str):
        ts = time.time()
        for g in games:
            if g.state == "pre":
                continue
            info = self.tracked.get(g.game_id)
            if info is None:
                if g.state == "post" or ts < self.retry_after.get(g.game_id, 0):
                    continue
                info = self.discover(g, now_iso)
                if info is RETRY:
                    self.retry_after[g.game_id] = ts + 20
                    continue
                info = info or {"skip": True}
                self.tracked[g.game_id] = info
            if info.get("skip"):
                continue
            self._game_tick(g, info, ts)

    def _game_tick(self, g: LiveGame, info: dict, ts: float):
        c = self.conn
        score = (g.home_score, g.away_score)
        if info["score"] is not None and score != info["score"]:
            info["goal_ts"] = ts
            self.log(f"[GOAL] {g.home} {score[0]}-{score[1]} {g.away} @ {g.minute:.0f}'")
        if info["score"] is None:
            info["goal_ts"] = None  # first sighting: unknown when the current score happened
        info["score"] = score
        c.execute("INSERT INTO game_ticks VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                  (ts, g.game_id, g.slug, g.home, g.away, g.state, g.status_name, g.minute,
                   score[0], score[1], g.red_home, g.red_away))
        if g.state == "post":
            self._settle(g, ts)
            info["skip"] = True
            c.commit()
            return

        quotes = {}  # ticker -> (label, kind, quote)
        for kind in KINDS:
            try:
                ms = list(self.client.iter_markets(
                    event_ticker=f"KX{info['prefix']}{kind}-{info['suffix']}", status="open"))
            except Exception as e:  # noqa: BLE001
                self.api_errors += 1
                self.log(f"[warn] {kind} fetch failed: {type(e).__name__}")
                continue
            for m in ms:
                q = quote_of(m)
                label = m.get("yes_sub_title") or m["ticker"]
                quotes[m["ticker"]] = (label, kind, q, m)
                c.execute("INSERT INTO quotes VALUES (?,?,?,?,?,?,?,?)",
                          (ts, g.game_id, m["ticker"], label, q["yes_bid"], q["yes_ask"], q["bid_sz"], q["ask_sz"]))
        self._delayed_fills(quotes)
        self._arbs(g, quotes, ts)
        self._signals(g, info, quotes, ts)
        c.commit()

    # ---- paper trades ---------------------------------------------------------------
    def _signals(self, g, info, quotes, ts):
        cfg = self.cfg
        if g.red_home or g.red_away or g.minute > cfg.max_minute or g.status_name == "STATUS_HALFTIME":
            return  # red cards are unmodelled; quotes at half time are stale/thin by construction
        lam, mu = self.model.expected_goals(info["model_h"], info["model_a"], neutral=False)
        share = remaining_share(g.period, g.minute, g.status_name)
        pr = Pricer(inplay_matrix(lam, mu, g.home_score, g.away_score, share))
        since_goal = None if info["goal_ts"] is None else ts - info["goal_ts"]
        tag = "latency" if since_goal is not None and since_goal <= cfg.latency_window_s else "model"
        lo, hi = (cfg.latency_band if tag == "latency" else cfg.model_band)
        best = {}  # market kind -> best candidate; one correlated bet per kind per score state
        for ticker, (label, kind, q, m) in quotes.items():
            if (g.game_id, kind, g.home_score, g.away_score) in self.traded:
                continue
            spec = parse_contract(ticker.split("-")[0], label, info["home_k"], info["away_k"])
            if spec is None:
                continue
            try:
                fair = pr.price(spec.name, spec.line)
            except (ValueError, KeyError):
                continue
            for side in ("yes", "no"):
                price = q["yes_ask"] if side == "yes" else (None if q["yes_bid"] is None else 1 - q["yes_bid"])
                size = q["ask_sz"] if side == "yes" else q["bid_sz"]
                if price is None or not (cfg.min_price <= price <= cfg.max_price) or size < cfg.min_ask_size:
                    continue
                p_win = fair if side == "yes" else 1 - fair
                if not (lo <= p_win <= hi):
                    continue
                n = min(cfg.max_size, size)
                fee = kalshi_fee(price, n)
                edge = p_win - price - fee / n
                if cfg.min_edge <= edge <= cfg.max_edge and (kind not in best or edge > best[kind][0]):
                    best[kind] = (edge, ticker, label, spec, side, p_win, price, n, fee)
        for kind, (edge, ticker, label, spec, side, p_win, price, n, fee) in best.items():
            self.traded.add((g.game_id, kind, g.home_score, g.away_score))
            cur = self.conn.execute(
                "INSERT INTO paper_trades (ts,game_id,ticker,label,contract,line,side,kind,fair,entry,size,fee,"
                "edge_net,minute,hs,as_,secs_since_goal) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (ts, g.game_id, ticker, label, spec.name, json.dumps(spec.line), side, tag, p_win, price, n, fee,
                 edge, g.minute, g.home_score, g.away_score, since_goal))
            self.pending[(ticker, side)] = cur.lastrowid
            self.log(f"[PAPER {tag}] {g.home} {g.home_score}-{g.away_score} {g.away} {g.minute:.0f}' "
                     f"BUY {side.upper()} {label} @ {price:.2f} fair {p_win:.2f} net edge {edge:+.3f} x{n:.0f}")

    def _delayed_fills(self, quotes):
        for (ticker, side), tid in list(self.pending.items()):
            if ticker not in quotes:
                continue
            q = quotes[ticker][2]
            price = q["yes_ask"] if side == "yes" else (None if q["yes_bid"] is None else 1 - q["yes_bid"])
            row = self.conn.execute("SELECT size FROM paper_trades WHERE id=?", (tid,)).fetchone()
            if price is None:   # quote vanished: the delayed order would not have filled
                self.conn.execute("UPDATE paper_trades SET entry_delayed=-1 WHERE id=?", (tid,))
            else:
                self.conn.execute("UPDATE paper_trades SET entry_delayed=?, fee_delayed=? WHERE id=?",
                                  (price, kalshi_fee(price, row["size"]), tid))
            del self.pending[(ticker, side)]

    def _settle(self, g: LiveGame, ts):
        rows = self.conn.execute("SELECT * FROM paper_trades WHERE game_id=? AND result_yes IS NULL",
                                 (g.game_id,)).fetchall()
        for r in rows:
            line = json.loads(r["line"])
            line = tuple(line) if isinstance(line, list) else line
            yes = int(_predicate_for(r["contract"], line)(g.home_score, g.away_score))
            win = yes if r["side"] == "yes" else 1 - yes
            pnl = r["size"] * (win - r["entry"]) - r["fee"]
            pnl_d = None
            if r["entry_delayed"] is not None and r["entry_delayed"] >= 0:
                pnl_d = r["size"] * (win - r["entry_delayed"]) - r["fee_delayed"]
            self.conn.execute("UPDATE paper_trades SET result_yes=?, pnl=?, pnl_delayed=? WHERE id=?",
                              (yes, pnl, pnl_d, r["id"]))
        if rows:
            self.log(f"[settled] {g.home} {g.home_score}-{g.away_score} {g.away}: {len(rows)} paper trades")

    # ---- structural arbitrage ------------------------------------------------------
    def _arbs(self, g, quotes, ts):
        def rec(kind, detail, cost, payout, fees, size):
            net = (payout - cost) * size - fees
            if net > 0:
                self.conn.execute("INSERT INTO arbs VALUES (?,?,?,?,?,?,?,?,?)",
                                  (ts, g.game_id, kind, detail, cost, payout, fees, net, size))
                self.log(f"[ARB {kind}] {g.home} v {g.away}: {detail} net ${net:.2f} on {size:.0f}")

        ml = [(k, v[2]) for k, v in quotes.items() if v[1] == "GAME"]
        if len(ml) == 3 and all(q["yes_ask"] and q["ask_sz"] >= 1 for _, q in ml):
            size = min(q["ask_sz"] for _, q in ml)
            cost = sum(q["yes_ask"] for _, q in ml)
            fees = sum(kalshi_fee(q["yes_ask"], size) for _, q in ml)
            rec("moneyline_buy_all_yes", f"asks sum {cost:.3f}", cost, 1.0, fees, size)
        if len(ml) == 3 and all(q["yes_bid"] and q["bid_sz"] >= 1 for _, q in ml):
            size = min(q["bid_sz"] for _, q in ml)
            cost = sum(1 - q["yes_bid"] for _, q in ml)      # buy NO on all three
            fees = sum(kalshi_fee(1 - q["yes_bid"], size) for _, q in ml)
            rec("moneyline_buy_all_no", f"bids sum {sum(q['yes_bid'] for _, q in ml):.3f}", cost, 2.0, fees, size)
        overs = []
        for k, (label, kind, q, _) in quotes.items():
            spec = parse_contract(k.split("-")[0], label, "", "") if kind == "TOTAL" else None
            if spec and spec.name == "over":
                overs.append((spec.line, q))
        overs.sort(key=lambda t: t[0])
        for (l1, q1), (l2, q2) in zip(overs, overs[1:]):   # Over l2 must be <= Over l1
            if q1["yes_ask"] and q2["yes_bid"] and q1["ask_sz"] >= 1 and q2["bid_sz"] >= 1:
                size = min(q1["ask_sz"], q2["bid_sz"])
                cost = q1["yes_ask"] + (1 - q2["yes_bid"])   # YES over l1 + NO over l2 pays >= $1
                fees = kalshi_fee(q1["yes_ask"], size) + kalshi_fee(1 - q2["yes_bid"], size)
                rec("totals_ladder_cross", f"ask O{l1} {q1['yes_ask']:.2f} < bid O{l2} {q2['yes_bid']:.2f}",
                    cost, 1.0, fees, size)
