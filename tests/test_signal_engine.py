from datetime import datetime

from wealth_lab.models import (
    FundFlowSnapshot,
    FundSignal,
    PatternTag,
    Quote,
    SectorFundFlowSnapshot,
)
from wealth_lab.signal_engine import FundSignalEngine


def test_buy_signal_with_volume_breakout() -> None:
    signal = FundSignalEngine().evaluate(
        fund_flow=_fund_flow(
            symbol="300750",
            super_large=260000000,
            large=180000000,
            small=-120000000,
            main_pct=7.1,
            change_pct=3.2,
            turnover_rate=2.8,
        ),
        quote=_quote(
            symbol="300750",
            price=245.2,
            change_pct=3.2,
            volume_ratio=2.3,
            high_20=244.0,
            low_20=210.0,
            sector="battery",
        ),
        sector_flow=_sector("battery", main=1550000000),
    )

    assert signal.fund_signal == FundSignal.BUY
    assert PatternTag.VOLUME_BREAKOUT in signal.pattern_tags
    assert PatternTag.KEY_POINT_CONFIRMED in signal.pattern_tags


def test_distribution_and_price_flow_divergence() -> None:
    signal = FundSignalEngine().evaluate(
        fund_flow=_fund_flow(
            symbol="002594",
            super_large=-180000000,
            large=-90000000,
            small=160000000,
            main_pct=-5.5,
            change_pct=4.6,
            turnover_rate=9.0,
        ),
        quote=_quote(
            symbol="002594",
            price=260.0,
            change_pct=4.6,
            volume_ratio=2.8,
            high_20=262.0,
            low_20=230.0,
            sector="auto",
        ),
        sector_flow=_sector("auto", main=450000000),
    )

    assert signal.fund_signal == FundSignal.SUSPECTED_DISTRIBUTION
    assert PatternTag.SUSPECTED_DISTRIBUTION in signal.pattern_tags
    assert PatternTag.PRICE_VOLUME_DIVERGENCE in signal.pattern_tags


def test_accumulation_signal_near_low_base() -> None:
    signal = FundSignalEngine().evaluate(
        fund_flow=_fund_flow(
            symbol="688981",
            super_large=90000000,
            large=50000000,
            small=-20000000,
            main_pct=4.2,
            change_pct=0.8,
            turnover_rate=3.9,
        ),
        quote=_quote(
            symbol="688981",
            price=82.0,
            change_pct=0.8,
            volume_ratio=1.4,
            high_20=92.0,
            low_20=78.0,
            sector="semiconductor",
        ),
        sector_flow=_sector("semiconductor", main=840000000),
    )

    assert signal.fund_signal == FundSignal.SUSPECTED_ACCUMULATION
    assert PatternTag.SUSPECTED_ACCUMULATION in signal.pattern_tags


def _fund_flow(
    symbol: str,
    super_large: float,
    large: float,
    small: float,
    main_pct: float,
    change_pct: float,
    turnover_rate: float,
) -> FundFlowSnapshot:
    return FundFlowSnapshot(
        symbol=symbol,
        name=symbol,
        timestamp=datetime(2026, 7, 6, 10, 30),
        super_large_net_inflow=super_large,
        large_net_inflow=large,
        medium_net_inflow=0,
        small_net_inflow=small,
        main_net_inflow_pct=main_pct,
        change_pct=change_pct,
        amount=1000000000,
        turnover_rate=turnover_rate,
        provider="test",
    )


def _quote(
    symbol: str,
    price: float,
    change_pct: float,
    volume_ratio: float,
    high_20: float,
    low_20: float,
    sector: str,
) -> Quote:
    return Quote(
        symbol=symbol,
        name=symbol,
        price=price,
        change_pct=change_pct,
        timestamp=datetime(2026, 7, 6, 10, 30),
        provider="test",
        amount=1000000000,
        volume=1000000,
        volume_ratio=volume_ratio,
        turnover_rate=3.0,
        high_20=high_20,
        low_20=low_20,
        sector=sector,
    )


def _sector(name: str, main: float) -> SectorFundFlowSnapshot:
    return SectorFundFlowSnapshot(
        name=name,
        sector_type="industry",
        timestamp=datetime(2026, 7, 6, 10, 30),
        super_large_net_inflow=main * 0.6,
        large_net_inflow=main * 0.4,
        medium_net_inflow=0,
        small_net_inflow=0,
        main_net_inflow_pct=5.0,
        change_pct=1.0,
        leading_stock=None,
        inflow_stock_count=20,
        provider="test",
    )

