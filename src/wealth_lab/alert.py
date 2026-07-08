"""Alert routing for monitor signals."""

from __future__ import annotations

from dataclasses import dataclass

from wealth_lab.models import FundSignal, StockSignal


ALERT_SIGNALS = {
    FundSignal.BUY,
    FundSignal.SELL,
    FundSignal.SUSPECTED_DISTRIBUTION,
    FundSignal.SUSPECTED_ACCUMULATION,
}


def build_alert_messages(
    signals: list[StockSignal],
    min_score: float = 80.0,
) -> list[str]:
    """Build alert messages from high-priority signals."""

    alerts: list[str] = []
    for signal in sorted(signals, key=lambda item: item.score, reverse=True):
        if signal.score < min_score and signal.fund_signal not in ALERT_SIGNALS:
            continue
        if signal.fund_signal == FundSignal.NONE:
            continue
        tags = ",".join(tag.value for tag in signal.pattern_tags)
        alerts.append(
            (
                f"{signal.symbol} {signal.name} "
                f"fund_signal={signal.fund_signal.value} tags={tags} "
                f"score={signal.score:.1f} "
                f"主力净流入={signal.fund_flow.main_net_inflow:.0f} "
                f"主力占比={signal.fund_flow.main_net_inflow_pct}"
            )
        )
    return alerts


@dataclass(frozen=True)
class ConsoleAlertSink:
    """Print alerts to stdout."""

    def send(self, messages: list[str]) -> None:
        """Send alert messages."""

        for message in messages:
            print(message)
