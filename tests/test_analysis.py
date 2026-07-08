from datetime import datetime

from wealth_lab.analysis import _latest_today_flow
from wealth_lab.models import FundFlowSnapshot, Quote


def test_latest_today_flow_falls_back_to_history_when_today_is_empty() -> None:
    collector = _FakeCollector()
    quote = Quote(
        symbol="000620",
        name="盈新发展",
        price=3.46,
        change_pct=-3.89,
        timestamp=datetime(2026, 7, 7, 10, 0),
        provider="test",
        amount=1_200_000_000,
        turnover_rate=7.5,
    )

    flow = _latest_today_flow(collector, quote)

    assert flow.period == "daily-fallback"
    assert flow.name == "盈新发展"
    assert flow.amount == 1_200_000_000
    assert flow.turnover_rate == 6.0
    assert flow.main_net_inflow_pct == -8.0


class _FakeCollector:
    def fetch_today(self, symbol: str) -> list[FundFlowSnapshot]:
        return []

    def fetch_history(self, symbol: str) -> list[FundFlowSnapshot]:
        return [
            FundFlowSnapshot(
                symbol=symbol,
                name="",
                timestamp=datetime(2026, 7, 6, 15, 0),
                super_large_net_inflow=-60_000_000,
                large_net_inflow=-40_000_000,
                medium_net_inflow=20_000_000,
                small_net_inflow=80_000_000,
                main_net_inflow_pct=-8.0,
                change_pct=-3.0,
                amount=1_000_000_000,
                turnover_rate=6.0,
                provider="test",
                period="daily",
            )
        ]
