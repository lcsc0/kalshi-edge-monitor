"""Threshold-cross alert interface (design §9, optional).

Interface only: no real push transport is wired in this phase (the monitor is
read-only and the operator trades manually). ``push`` is a documented stub that
raises ``NotImplementedError`` so a future SP can plug in a transport (SMS, push,
Slack) without changing the decision/formatting logic here.
"""
from dataclasses import dataclass

from kalshi_edge.edge.engine import EdgeSignal


@dataclass
class Alert:
    ticker: str
    message: str


def should_alert(signal: EdgeSignal, threshold: float) -> bool:
    """Fire when a *live* (non-suppressed) signal's edge crosses ``threshold``."""
    if signal.suppressed:
        return False
    return abs(signal.edge) >= threshold


def format_alert(signal: EdgeSignal) -> str:
    return (f"{signal.ticker}: buy {signal.side} | edge {signal.edge:+.2f} "
            f"(model {signal.model_fair:.2f} vs market {signal.market_implied:.2f})")


def to_alert(signal: EdgeSignal) -> Alert:
    return Alert(ticker=signal.ticker, message=format_alert(signal))


def push(alert: Alert) -> None:
    """Deliver an alert. Interface-only stub — no transport in this phase."""
    raise NotImplementedError(
        "push transport is out of scope for the monitor-only phase; "
        "wire a real service (SMS/push/Slack) in a later SP")
