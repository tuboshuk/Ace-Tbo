from datetime import date, timedelta

from wealth_lab.models import Bar, PortfolioSnapshot
from wealth_lab.replay import ReplayResult
from wealth_lab.volume_replay import build_volume_price_replay


def test_volume_price_replay_classifies_expansion_and_shrink_nodes() -> None:
    start = date(2026, 1, 1)
    bars = [
        _bar(start + timedelta(days=index), close=10.0 + index * 0.01, volume=1000)
        for index in range(20)
    ]
    bars.extend(
        [
            _bar(start + timedelta(days=20), close=10.5, volume=2500, change_pct=4.0),
            _bar(start + timedelta(days=21), close=10.25, high=10.7, volume=3000, change_pct=-2.4),
            _bar(start + timedelta(days=22), close=10.1, volume=600, change_pct=-1.5),
        ]
    )
    result = _result(bars)

    replay = build_volume_price_replay(result, window=20)

    node_types = [node.node_type for node in replay.nodes]
    assert "volume_breakout" in node_types
    assert "high_volume_failed_breakout" in node_types
    assert "shrink_pullback" in node_types
    assert replay.expansion_nodes >= 2
    assert replay.shrink_nodes >= 1


def test_volume_price_replay_uses_previous_window_only() -> None:
    start = date(2026, 1, 1)
    bars = [
        _bar(start + timedelta(days=index), close=10.0, volume=1000)
        for index in range(5)
    ]
    bars.append(_bar(start + timedelta(days=5), close=10.2, volume=1800))
    bars.append(_bar(start + timedelta(days=6), close=10.3, volume=100000))

    replay = build_volume_price_replay(_result(bars), window=5)
    target = next(node for node in replay.nodes if node.trade_date == start + timedelta(days=5))

    assert target.volume_ratio == 1.8


def _result(bars: list[Bar]) -> ReplayResult:
    return ReplayResult(
        symbol="000001",
        name="test",
        bars_count=len(bars),
        fund_flows_count=0,
        first_bar_date=bars[0].trade_date,
        last_bar_date=bars[-1].trade_date,
        signals=[],
        decisions=[],
        fills=[],
        equity_curve=[PortfolioSnapshot(bars[-1].trade_date, 100000, 0, 100000, {})],
        missing_fund_flow_dates=[],
        skipped_orders=[],
        initial_cash=100000,
        final_value=100000,
        total_return=0.0,
        max_drawdown=0.0,
        bars=bars,
    )


def _bar(
    trade_date: date,
    *,
    close: float,
    volume: int,
    high: float | None = None,
    change_pct: float = 1.0,
) -> Bar:
    high_value = high if high is not None else close
    return Bar(
        symbol="000001",
        trade_date=trade_date,
        open=close,
        high=high_value,
        low=close * 0.98,
        close=close,
        volume=volume,
        amount=close * volume,
        change_pct=change_pct,
        turnover_rate=5.0,
    )
