from datetime import date, datetime

from wealth_lab.behavior_model import build_trading_state_model
from wealth_lab.models import (
    Fill,
    FundFlowSnapshot,
    FundSignal,
    MainForceProfile,
    OrderSide,
    PatternTag,
    PortfolioSnapshot,
    Quote,
    StockSignal,
)
from wealth_lab.replay import ReplayResult


def test_trading_state_model_marks_buy_signal_as_probe_ready() -> None:
    result = _result(
        _signal(
            fund_signal=FundSignal.BUY,
            pattern_tags=(PatternTag.VOLUME_BREAKOUT,),
            distribution_score=20,
        )
    )

    state = build_trading_state_model(result)

    assert state.trading_mode == "PROBE_READY"
    assert state.buy_state == "ready"
    assert state.fund_data.flow_bias == "sustained_inflow"
    assert any(node.node_id == "buy_path" and node.status == "pass" for node in state.nodes)


def test_trading_state_model_marks_failed_breakout_as_sell_ready() -> None:
    signal = _signal(
        fund_signal=FundSignal.SELL,
        pattern_tags=(PatternTag.FAILED_BREAKOUT,),
        main_flow=-2_000_000,
        main_pct=-7.0,
        distribution_score=85,
    )
    result = _result(
        signal,
        fills=[
            Fill(
                symbol="000001",
                side=OrderSide.BUY,
                quantity=1000,
                price=10.0,
                trade_date=date(2026, 1, 1),
                gross_amount=10000,
                fees=0,
                reason="entry",
            )
        ],
        positions={"000001": 1000},
    )

    state = build_trading_state_model(result)

    assert state.trading_mode == "SELL_READY"
    assert state.sell_state == "ready"
    assert state.behavior_action.phase == "distribution_or_failed_breakout"


def test_trading_state_model_marks_flat_failed_breakout_as_wait_sell_risk() -> None:
    result = _result(
        _signal(
            fund_signal=FundSignal.SELL,
            pattern_tags=(PatternTag.FAILED_BREAKOUT,),
            main_flow=-2_000_000,
            main_pct=-7.0,
            distribution_score=85,
        )
    )

    state = build_trading_state_model(result)

    assert state.trading_mode == "WAIT_SELL_RISK"
    assert state.sell_state == "avoid_entry"


def _result(
    signal: StockSignal,
    fills: list[Fill] | None = None,
    positions: dict[str, int] | None = None,
) -> ReplayResult:
    return ReplayResult(
        symbol="000001",
        name="test",
        bars_count=10,
        fund_flows_count=10,
        first_bar_date=date(2026, 1, 1),
        last_bar_date=date(2026, 1, 10),
        signals=[signal],
        decisions=[],
        fills=fills or [],
        equity_curve=[
            PortfolioSnapshot(date(2026, 1, 10), 100000, 0, 100000, positions or {})
        ],
        missing_fund_flow_dates=[],
        skipped_orders=[],
        initial_cash=100000,
        final_value=100000,
        total_return=0,
        max_drawdown=0,
    )


def _signal(
    fund_signal: FundSignal,
    pattern_tags: tuple[PatternTag, ...],
    main_flow: float = 2_000_000,
    main_pct: float = 8.0,
    distribution_score: float = 20,
) -> StockSignal:
    timestamp = datetime(2026, 1, 10, 15)
    super_large = main_flow * 0.6
    large = main_flow * 0.4
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
            price=10.0,
            change_pct=3.0 if main_flow > 0 else -3.0,
            timestamp=timestamp,
            provider="test",
            volume_ratio=2.0,
        ),
        fund_flow=FundFlowSnapshot(
            symbol="000001",
            name="test",
            timestamp=timestamp,
            super_large_net_inflow=super_large,
            large_net_inflow=large,
            medium_net_inflow=0,
            small_net_inflow=-500_000 if main_flow > 0 else 500_000,
            main_net_inflow_pct=main_pct,
            change_pct=3.0 if main_flow > 0 else -3.0,
            amount=100_000_000,
            turnover_rate=8.0,
            provider="test",
            period="daily",
        ),
        intent_profile=MainForceProfile(
            trade_date=date(2026, 1, 10),
            close=10.0,
            daily_trend="up" if main_flow > 0 else "down",
            weekly_trend="up" if main_flow > 0 else "down",
            monthly_trend="up" if main_flow > 0 else "down",
            stage="markup_confirmed" if main_flow > 0 else "distribution_risk",
            vwap_60=9.5,
            vwap_120=9.0,
            close_vs_vwap_60_pct=5.0,
            close_vs_vwap_120_pct=11.0,
            turnover_20=60,
            turnover_60=120,
            main_flow_3=main_flow * 3,
            main_flow_5=main_flow * 5,
            main_flow_10=main_flow * 10,
            obv_slope_20=0.2 if main_flow > 0 else -0.2,
            adl_slope_20=0.2 if main_flow > 0 else -0.2,
            accumulation_score=70 if main_flow > 0 else 20,
            markup_score=75 if main_flow > 0 else 10,
            distribution_score=distribution_score,
        ),
    )
