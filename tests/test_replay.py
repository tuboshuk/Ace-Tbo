from datetime import date, datetime, timedelta

from wealth_lab.models import Bar, FundFlowSnapshot, OrderSide
from wealth_lab.replay import HistoricalReplayRunner


def test_replay_executes_next_open_and_exits_on_distribution() -> None:
    start = date(2026, 1, 1)
    bars = [
        _bar("000001", start + timedelta(days=index), 10.0 + index * 0.03)
        for index in range(75)
    ]
    breakout_date = start + timedelta(days=75)
    failure_date = start + timedelta(days=76)
    exit_date = start + timedelta(days=77)
    bars.extend(
        [
            _bar("000001", breakout_date, 12.25, volume=2_000_000, change_pct=3.0),
            _bar("000001", failure_date, 11.8, volume=3_200_000, change_pct=-4.8),
            _bar("000001", exit_date, 11.7, change_pct=-0.8),
        ]
    )
    flows = [
        _flow(breakout_date, 4_000_000, 2_000_000, -800_000, 9.0, 3.0),
        _flow(failure_date, -4_000_000, -2_000_000, 2_000_000, -9.0, -4.8),
    ]

    result = HistoricalReplayRunner(bars, flows, initial_cash=100000).run()

    assert len(result.fills) == 2
    assert result.fills[0].side == OrderSide.BUY
    assert result.fills[0].trade_date == failure_date
    assert result.fills[1].side == OrderSide.SELL
    assert result.fills[1].trade_date == exit_date
    assert result.signals[0].intent_profile is not None


def _bar(
    symbol: str,
    trade_date: date,
    close: float,
    volume: int = 1_000_000,
    change_pct: float = 1.0,
) -> Bar:
    return Bar(
        symbol=symbol,
        trade_date=trade_date,
        open=close,
        high=close,
        low=close * 0.98,
        close=close,
        volume=volume,
        amount=close * volume,
        change_pct=change_pct,
        turnover_rate=5.0,
    )


def _flow(
    trade_date: date,
    super_large: float,
    large: float,
    small: float,
    main_pct: float,
    change_pct: float,
) -> FundFlowSnapshot:
    return FundFlowSnapshot(
        symbol="000001",
        name="test",
        timestamp=datetime.combine(trade_date, datetime.min.time()),
        super_large_net_inflow=super_large,
        large_net_inflow=large,
        medium_net_inflow=0,
        small_net_inflow=small,
        main_net_inflow_pct=main_pct,
        change_pct=change_pct,
        amount=10_000_000,
        turnover_rate=5.0,
        provider="test",
        period="daily",
    )
