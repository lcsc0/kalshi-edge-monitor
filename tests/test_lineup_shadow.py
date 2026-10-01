from kalshi_edge.data.cache import connect
from kalshi_edge.data.club_results import load_fixtures_csv
from kalshi_edge.edge.club_shadow import build_club_signals
from kalshi_edge.edge.engine import EdgeEngine
from kalshi_edge.lineup import store
from kalshi_edge.pricer.pricer import Pricer
from kalshi_edge.model.poisson import score_matrix
from tests.test_club_shadow import MARKETS, NOW, FakeClient, _fixtures, _model


def _variants(model, hm=0.8, am=1.0):
    def variants_for(home, away, kickoff, event):
        lam, mu = model.expected_goals(home, away, neutral=False)
        pr = Pricer(score_matrix(lam * hm, mu * am, model.fit.rho, model.max_goals), home, away)
        return {"stat": (pr, {"home_mult": hm, "away_mult": am})}
    return variants_for


def _run(**kw):
    fix = connect()
    load_fixtures_csv(fix, _fixtures())
    model = _model()
    return build_club_signals(FakeClient(MARKETS), model, fix, EdgeEngine(), now=NOW,
                              leagues=["EPL"], **kw), model


def test_default_call_unchanged_by_new_hooks():
    (signals, stats), _ = _run()
    assert len(signals) == 5 and all("variant" not in s.analysis for s in signals)


def test_variants_priced_off_same_book_and_tagged():
    (signals, stats), model = _run(variants_for=_variants(_model()))
    assert len(signals) == 10
    by = {(s.ticker, s.analysis["variant"]): s for s in signals}
    base, stat = by[("KXEPLGAME-26OCT11LFCBRE-LFC", "base")], by[("KXEPLGAME-26OCT11LFCBRE-LFC", "stat")]
    assert stat.market_implied == base.market_implied          # same order book
    assert stat.model_fair < base.model_fair                   # home goals cut -> home win less likely
    assert base.analysis["event"] == "26OCT11LFCBRE" and base.analysis["kickoff"].startswith("2026-10-11T14:00")


def test_variants_none_skips_fixture_and_window_filters():
    (signals, stats), _ = _run(variants_for=lambda *a: None)
    assert signals == [] and stats["no_lineup"] == 1
    (signals, stats), _ = _run(max_lead_minutes=60, variants_for=_variants(_model()))
    assert signals == [] and stats["outside_window"] == 1


def test_store_logs_once_settles_and_scores():
    (signals, _), _ = _run(variants_for=_variants(_model()))
    conn = connect()
    store.ensure_store(conn)
    for s in signals:
        store.log_variant_signal(conn, s)
        store.log_variant_signal(conn, s)                      # duplicate is ignored
    assert conn.execute("SELECT COUNT(*) FROM lineup_signal").fetchone()[0] == 10
    assert store.logged_events(conn) == {"26OCT11LFCBRE"}
    assert store.scorecard(conn) == []                         # nothing settled yet
    out = store.settle(conn, lambda t: t.endswith("LFC"))      # LFC leg YES, everything else NO
    assert out["settled"] == 5
    (row,) = store.scorecard(conn)
    assert row["variant"] == "stat" and row["n"] == 5 and row["moved"] == 5
    assert "stat" in store.render_scorecard([row])
