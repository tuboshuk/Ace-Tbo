from datetime import date, datetime, timedelta
from statistics import fmean

from wealth_lab.intent_features import build_main_force_profile
from wealth_lab.models import Bar, FundFlowSnapshot


def test_main_force_profile_uses_current_and_past_data_only() -> None:
    start = date(2026, 1, 1)
    bars = [
        _bar(start + timedelta(days=index), 10.0 + index * 0.1)
        for index in range(65)
    ]
    flows = [
        _flow(start + timedelta(days=58), 1_000_000, 500_000),
        _flow(start + timedelta(days=61), 2_000_000, 500_000),
        _flow(start + timedelta(days=64), -99_000_000, -1_000_000),
    ]

    profile = build_main_force_profile(bars, flows, index=61)

    expected_vwap_60 = fmean(bar.close for bar in bars[2:62])
    assert profile.trade_date == start + timedelta(days=61)
    assert profile.vwap_60 == expected_vwap_60
    assert profile.main_flow_3 == 4_000_000
    assert profile.main_flow_5 == 4_000_000
    assert profile.main_flow_10 == 4_000_000
    assert profile.close_vs_vwap_60_pct is not None
    assert "main_flow_5=4000000" in profile.evidence


def test_main_force_profile_scores_markup_context() -> None:
    start = date(2026, 1, 1)
    bars = [
        _bar(start + timedelta(days=index), 10.0 + index * 0.04)
        for index in range(75)
    ]
    bars.append(_bar(start + timedelta(days=75), 14.0, volume=3_000_000))
    flows = [
        _flow(start + timedelta(days=75), 5_000_000, 2_000_000),
    ]

    profile = build_main_force_profile(bars, flows, index=75)

    assert profile.markup_score >= 55
    assert profile.distribution_score <= 65
    assert profile.stage in {"markup_confirmed", "accumulation_watch", "neutral"}


def _bar(
    trade_date: date,
    close: float,
    volume: int = 1_000_000,
) -> Bar:
    return Bar(
        symbol="000001",
        trade_date=trade_date,
        open=close,
        high=close,
        low=close * 0.98,
        close=close,
        volume=volume,
        amount=close * volume,
        change_pct=1.0,
        turnover_rate=5.0,
    )


def _flow(
    trade_date: date,
    super_large: float,
    large: float,
) -> FundFlowSnapshot:
    return FundFlowSnapshot(
        symbol="000001",
        name="test",
        timestamp=datetime.combine(trade_date, datetime.min.time()),
        super_large_net_inflow=super_large,
        large_net_inflow=large,
        medium_net_inflow=0,
        small_net_inflow=-100_000,
        main_net_inflow_pct=8.0,
        change_pct=1.0,
        amount=10_000_000,
        turnover_rate=5.0,
        provider="test",
        period="daily",
    )
