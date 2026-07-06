import pytest

from kalshi_edge.edge.engine import EdgeSignal
from kalshi_edge.report.alerts import Alert, should_alert, format_alert, push


def _sig(edge=0.08, suppressed=False, reason=None):
    return EdgeSignal(
        ticker="KXWCGAME-X", side="yes", model_fair=0.70, market_implied=0.62,
        edge=edge, fillable_size=100, slippage=0.0, suppressed=suppressed,
        suppression_reason=reason, analysis={"home": "X", "away": "Y"})


def test_should_alert_fires_on_threshold_cross():
    assert should_alert(_sig(edge=0.08), threshold=0.05) is True


def test_should_alert_silent_below_threshold():
    assert should_alert(_sig(edge=0.02), threshold=0.05) is False


def test_should_alert_never_fires_for_suppressed():
    assert should_alert(_sig(edge=0.30, suppressed=True, reason="absurd_edge"),
                        threshold=0.05) is False


def test_format_alert_mentions_ticker_side_and_edge():
    msg = format_alert(_sig(edge=0.08))
    assert "KXWCGAME-X" in msg
    assert "yes" in msg
    assert "0.08" in msg


def test_push_is_interface_only_stub():
    with pytest.raises(NotImplementedError):
        push(Alert(ticker="KXWCGAME-X", message="edge 0.08"))
