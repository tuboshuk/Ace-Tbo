from datetime import datetime

from wealth_lab.accumulation_proof import build_point_in_time_proof_context
from wealth_lab.models import (
    FundFlowSnapshot,
    FundSignal,
    MainForceProfile,
    OrderSide,
    PatternTag,
    Position,
    Quote,
    StockSignal,
)
from wealth_lab.paper import PaperBroker
from wealth_lab.trade_discipline import (
    DisciplineConfig,
    TradeDiscipline,
    discipline_config_for_mode,
)


def test_trade_discipline_waits_for_disguised_accumulation_confirmation() -> None:
    decision = TradeDiscipline().decide(
        _disguised_accumulation_signal(),
        PaperBroker(initial_cash=100000),
    )

    assert decision.side is None
    assert decision.reason.startswith("wait_accumulation_proof")


def test_trade_discipline_allows_small_probe_when_point_in_time_history_supports() -> None:
    signals = [
        _disguised_accumulation_signal(datetime(2026, 1, 1, 15)),
        _neutral_signal(datetime(2026, 1, 2, 15), 10.2, 300_000),
        _neutral_signal(datetime(2026, 1, 3, 15), 10.4, 300_000),
        _disguised_accumulation_signal(datetime(2026, 1, 4, 15)),
    ]
    proof_context = build_point_in_time_proof_context(
        signals,
        index=3,
        horizon=2,
        min_cases=1,
        min_confirmation_rate_pct=60.0,
    )

    decision = TradeDiscipline(
        DisciplineConfig(
            enable_accumulation_proof_probe=True,
            min_accumulation_proof_cases=1,
        )
    ).decide(
        signals[-1],
        PaperBroker(initial_cash=100000),
        proof_context=proof_context,
    )

    assert decision.side == OrderSide.BUY
    assert decision.reason.startswith("proof_probe_entry")
    assert decision.target_weight == 0.08


def test_active_probe_buys_possible_setup_with_reward_risk_gate() -> None:
    signal = _active_probe_signal(price=9.4, high_20=10.0, low_20=8.0, vwap_60=9.2)

    decision = TradeDiscipline(discipline_config_for_mode("active-probe")).decide(
        signal,
        PaperBroker(initial_cash=100000),
    )

    assert decision.side == OrderSide.BUY
    assert decision.reason.startswith("active_probe_entry")
    assert decision.target_weight == 0.08


def test_active_probe_blocks_poor_reward_risk_setup() -> None:
    signal = _active_probe_signal(price=9.9, high_20=10.0, low_20=9.0, vwap_60=9.7)

    decision = TradeDiscipline(discipline_config_for_mode("active-probe")).decide(
        signal,
        PaperBroker(initial_cash=100000),
    )

    assert decision.side is None


def test_active_probe_sells_on_inferred_exit_pressure() -> None:
    broker = PaperBroker(initial_cash=100000)
    broker.positions["000001"] = Position(
        symbol="000001",
        quantity=1000,
        avg_cost=10.5,
    )
    signal = _active_probe_signal(
        price=10.0,
        high_20=10.8,
        low_20=9.0,
        vwap_60=10.2,
        fund_signal=FundSignal.DIVERGENCE,
        pattern_tags=(PatternTag.PRICE_VOLUME_DIVERGENCE,),
        main_pct=-5.5,
        super_large=-1_000_000,
        large=-500_000,
        change_pct=-1.5,
        markup_score=40.0,
        distribution_score=62.0,
    )

    decision = TradeDiscipline(discipline_config_for_mode("active-probe")).decide(
        signal,
        broker,
    )

    assert decision.side == OrderSide.SELL
    assert decision.reason.startswith("inferred_exit")


def _disguised_accumulation_signal(timestamp: datetime | None = None) -> StockSignal:
    timestamp = timestamp or datetime(2026, 1, 1, 15)
    return StockSignal(
        symbol="000001",
        name="test",
        timestamp=timestamp,
        fund_signal=FundSignal.SELL,
        pattern_tags=(PatternTag.FAILED_BREAKOUT,),
        anomalies=(),
        score=80,
        reasons=(),
        quote=Quote(
            symbol="000001",
            name="test",
            price=10.0,
            change_pct=-3.0,
            timestamp=timestamp,
            provider="test",
        ),
        fund_flow=FundFlowSnapshot(
            symbol="000001",
            name="test",
            timestamp=timestamp,
            super_large_net_inflow=-700_000,
            large_net_inflow=-300_000,
            medium_net_inflow=0,
            small_net_inflow=800_000,
            main_net_inflow_pct=-6.0,
            change_pct=-3.0,
            amount=100_000_000,
            turnover_rate=8.0,
            provider="test",
            period="daily",
        ),
    )


def _neutral_signal(timestamp: datetime, price: float, main_flow: float) -> StockSignal:
    return StockSignal(
        symbol="000001",
        name="test",
        timestamp=timestamp,
        fund_signal=FundSignal.NONE,
        pattern_tags=(PatternTag.NO_ACTION,),
        anomalies=(),
        score=20,
        reasons=(),
        quote=Quote(
            symbol="000001",
            name="test",
            price=price,
            change_pct=1.0,
            timestamp=timestamp,
            provider="test",
        ),
        fund_flow=FundFlowSnapshot(
            symbol="000001",
            name="test",
            timestamp=timestamp,
            super_large_net_inflow=main_flow,
            large_net_inflow=0,
            medium_net_inflow=0,
            small_net_inflow=-100_000,
            main_net_inflow_pct=3.0,
            change_pct=1.0,
            amount=100_000_000,
            turnover_rate=5.0,
            provider="test",
            period="daily",
        ),
    )


def _active_probe_signal(
    *,
    price: float,
    high_20: float,
    low_20: float,
    vwap_60: float,
    fund_signal: FundSignal = FundSignal.SUSPECTED_ACCUMULATION,
    pattern_tags: tuple[PatternTag, ...] = (PatternTag.VCP_SETUP,),
    main_pct: float = 8.5,
    super_large: float = 700_000,
    large: float = 500_000,
    change_pct: float = 1.0,
    markup_score: float = 50.0,
    distribution_score: float = 20.0,
) -> StockSignal:
    timestamp = datetime(2026, 1, 1, 15)
    return StockSignal(
        symbol="000001",
        name="test",
        timestamp=timestamp,
        fund_signal=fund_signal,
        pattern_tags=pattern_tags,
        anomalies=(),
        score=75,
        reasons=(),
        quote=Quote(
            symbol="000001",
            name="test",
            price=price,
            change_pct=change_pct,
            timestamp=timestamp,
            provider="test",
            volume_ratio=1.4,
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
            small_net_inflow=-200_000,
            main_net_inflow_pct=main_pct,
            change_pct=change_pct,
            amount=100_000_000,
            turnover_rate=5.0,
            provider="test",
            period="daily",
        ),
        intent_profile=MainForceProfile(
            trade_date=timestamp.date(),
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
            main_flow_3=2_000_000,
            main_flow_5=3_000_000,
            main_flow_10=4_000_000,
            obv_slope_20=0.2,
            adl_slope_20=0.2,
            accumulation_score=55.0,
            markup_score=markup_score,
            distribution_score=distribution_score,
        ),
    )
