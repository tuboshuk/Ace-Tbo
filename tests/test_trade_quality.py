from datetime import date, datetime

from wealth_lab.models import (
    FundFlowSnapshot,
    FundSignal,
    MainForceProfile,
    PatternTag,
    Quote,
    StockSignal,
)
from wealth_lab.trade_quality import (
    estimate_entry_quality,
    estimate_inferred_exit_pressure,
)


def test_entry_quality_passes_when_reward_risk_is_acceptable() -> None:
    signal = _signal(price=10.0, high_20=9.8, low_20=8.0, vwap_60=9.4)

    quality = estimate_entry_quality(signal, min_reward_risk=1.2)

    assert quality.known is True
    assert quality.passed is True
    assert quality.reward_risk is not None
    assert quality.reward_risk > 2.0
    assert quality.risk_pct is not None
    assert quality.risk_pct < 8.0


def test_entry_quality_blocks_poor_reward_risk() -> None:
    signal = _signal(price=10.0, high_20=9.8, low_20=9.0, vwap_60=9.6)

    quality = estimate_entry_quality(signal, min_reward_risk=1.2)

    assert quality.known is True
    assert quality.passed is False
    assert quality.reason.startswith("reward_risk_or_risk_pct_failed")


def test_inferred_exit_pressure_triggers_on_negative_flow_and_weak_price() -> None:
    signal = _signal(
        price=9.8,
        high_20=10.5,
        low_20=8.8,
        vwap_60=10.0,
        fund_signal=FundSignal.DIVERGENCE,
        pattern_tags=(PatternTag.PRICE_VOLUME_DIVERGENCE,),
        main_pct=-5.0,
        super_large=-1_000_000,
        large=-500_000,
        change_pct=-1.5,
        distribution_score=62.0,
        markup_score=40.0,
    )

    pressure = estimate_inferred_exit_pressure(signal, avg_cost=10.2)

    assert pressure.triggered is True
    assert pressure.score >= 55.0
    assert "main_flow_negative" in pressure.reasons


def _signal(
    *,
    price: float,
    high_20: float,
    low_20: float,
    vwap_60: float,
    fund_signal: FundSignal = FundSignal.BUY,
    pattern_tags: tuple[PatternTag, ...] = (PatternTag.VOLUME_BREAKOUT,),
    main_pct: float = 6.0,
    super_large: float = 1_000_000,
    large: float = 500_000,
    change_pct: float = 2.0,
    distribution_score: float = 20.0,
    markup_score: float = 65.0,
) -> StockSignal:
    timestamp = datetime(2026, 1, 1, 15)
    return StockSignal(
        symbol="000001",
        name="test",
        timestamp=timestamp,
        fund_signal=fund_signal,
        pattern_tags=pattern_tags,
        anomalies=(),
        score=80,
        reasons=(),
        quote=Quote(
            symbol="000001",
            name="test",
            price=price,
            change_pct=change_pct,
            timestamp=timestamp,
            provider="test",
            volume_ratio=1.8,
            high_20=high_20,
            low_20=low_20,
        ),
        fund_flow=FundFlowSnapshot(
            symbol="000001",
            name="test",
            timestamp=timestamp,
            super_large_net_inflow=super_large,
            large_net_inflow=large,
            medium_net_inflow=0,
            small_net_inflow=-300_000,
            main_net_inflow_pct=main_pct,
            change_pct=change_pct,
            amount=100_000_000,
            turnover_rate=5.0,
            provider="test",
            period="daily",
        ),
        intent_profile=MainForceProfile(
            trade_date=date(2026, 1, 1),
            close=price,
            daily_trend="up",
            weekly_trend="up",
            monthly_trend="up",
            stage="accumulation_watch",
            vwap_60=vwap_60,
            vwap_120=vwap_60 - 0.2,
            close_vs_vwap_60_pct=(price / vwap_60 - 1) * 100,
            close_vs_vwap_120_pct=(price / (vwap_60 - 0.2) - 1) * 100,
            turnover_20=50,
            turnover_60=120,
            main_flow_3=3_000_000,
            main_flow_5=4_000_000,
            main_flow_10=5_000_000,
            obv_slope_20=0.2,
            adl_slope_20=0.2,
            accumulation_score=55.0,
            markup_score=markup_score,
            distribution_score=distribution_score,
        ),
    )
