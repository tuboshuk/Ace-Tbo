from datetime import date, datetime

from wealth_lab.decision_explainer import (
    explain_entry_opportunities,
    explain_latest_action,
)
from wealth_lab.models import (
    FundFlowSnapshot,
    FundSignal,
    MainForceProfile,
    PatternTag,
    PortfolioSnapshot,
    Quote,
    StockSignal,
)
from wealth_lab.replay import ReplayResult
from wealth_lab.trade_discipline import discipline_config_for_mode


def test_explain_latest_action_waits_when_latest_signal_is_sell() -> None:
    result = _result(
        _signal(
            fund_signal=FundSignal.SELL,
            pattern_tags=(PatternTag.FAILED_BREAKOUT,),
        )
    )

    explanation = explain_latest_action(result)

    assert explanation.action == "WAIT"
    assert explanation.position_state == "flat"
    assert any(
        check.name == "breakout_fund_signal" and check.status == "fail"
        for check in explanation.buy_checks
    )
    assert any(
        check.name == "sell_failed_breakout" and check.status == "pass"
        for check in explanation.sell_checks
    )


def test_explain_latest_action_buys_confirmed_breakout_when_flat() -> None:
    result = _result(
        _signal(
            fund_signal=FundSignal.BUY,
            pattern_tags=(PatternTag.VOLUME_BREAKOUT,),
        )
    )

    explanation = explain_latest_action(result)

    assert explanation.action == "BUY_NEXT_OPEN"
    assert all(
        check.status == "pass"
        for check in explanation.buy_checks
        if check.name.startswith("breakout")
    )


def test_explain_entry_opportunities_allows_pursuit_probe() -> None:
    signal = _signal(
        fund_signal=FundSignal.BUY,
        pattern_tags=(PatternTag.VOLUME_BREAKOUT,),
    )
    signal = StockSignal(
        symbol=signal.symbol,
        name=signal.name,
        timestamp=signal.timestamp,
        fund_signal=signal.fund_signal,
        pattern_tags=signal.pattern_tags,
        anomalies=signal.anomalies,
        score=signal.score,
        reasons=signal.reasons,
        quote=signal.quote,
        fund_flow=FundFlowSnapshot(
            symbol=signal.fund_flow.symbol,
            name=signal.fund_flow.name,
            timestamp=signal.fund_flow.timestamp,
            super_large_net_inflow=signal.fund_flow.super_large_net_inflow,
            large_net_inflow=signal.fund_flow.large_net_inflow,
            medium_net_inflow=signal.fund_flow.medium_net_inflow,
            small_net_inflow=signal.fund_flow.small_net_inflow,
            main_net_inflow_pct=signal.fund_flow.main_net_inflow_pct,
            change_pct=signal.fund_flow.change_pct,
            amount=signal.fund_flow.amount,
            turnover_rate=20.0,
            provider=signal.fund_flow.provider,
            period=signal.fund_flow.period,
        ),
        intent_profile=signal.intent_profile,
    )

    opportunities = explain_entry_opportunities(_result(signal))

    assert len(opportunities) == 1
    assert opportunities[0].status == "TRADE_READY_PURSUIT"
    assert opportunities[0].failed_gates == ()


def test_explain_entry_opportunities_keeps_failed_breakout_as_observation() -> None:
    signal = _signal(
        fund_signal=FundSignal.BUY,
        pattern_tags=(PatternTag.VOLUME_BREAKOUT, PatternTag.FAILED_BREAKOUT),
    )

    opportunities = explain_entry_opportunities(_result(signal))

    assert len(opportunities) == 1
    assert opportunities[0].status == "OBSERVE_RISK_GATED"
    assert "breakout_no_failed_or_distribution_tag" in opportunities[0].failed_gates


def test_explain_entry_opportunities_marks_active_probe_ready() -> None:
    signal = _signal(
        fund_signal=FundSignal.SUSPECTED_ACCUMULATION,
        pattern_tags=(PatternTag.VCP_SETUP,),
        high_20=10.8,
        low_20=8.0,
        accumulation_score=50,
    )

    opportunities = explain_entry_opportunities(
        _result(signal),
        discipline_config_for_mode("active-probe"),
    )

    assert len(opportunities) == 1
    assert opportunities[0].status == "TRADE_READY_ACTIVE_PROBE"
    assert opportunities[0].failed_gates == ()


def test_explain_entry_opportunities_marks_disguised_accumulation_as_proof_gated() -> None:
    signal = _disguised_accumulation_signal()

    opportunities = explain_entry_opportunities(_result(signal))

    assert len(opportunities) == 1
    assert opportunities[0].status == "OBSERVE_RISK_GATED"
    assert "proof_probe_resolved_cases" in opportunities[0].failed_gates


def _result(signal: StockSignal) -> ReplayResult:
    return ReplayResult(
        symbol="000001",
        name="test",
        bars_count=1,
        fund_flows_count=1,
        first_bar_date=date(2026, 1, 1),
        last_bar_date=date(2026, 1, 1),
        signals=[signal],
        decisions=[],
        fills=[],
        equity_curve=[PortfolioSnapshot(date(2026, 1, 1), 100000, 0, 100000, {})],
        missing_fund_flow_dates=[],
        skipped_orders=[],
        initial_cash=100000,
        final_value=100000,
        total_return=0,
        max_drawdown=0,
    )


def _disguised_accumulation_signal() -> StockSignal:
    timestamp = datetime(2026, 1, 1, 15)
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


def _signal(
    fund_signal: FundSignal,
    pattern_tags: tuple[PatternTag, ...],
    high_20: float | None = None,
    low_20: float | None = None,
    accumulation_score: float = 70,
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
            price=10.0,
            change_pct=3.0,
            timestamp=timestamp,
            provider="test",
            volume_ratio=2.0,
            high_20=high_20,
            low_20=low_20,
        ),
        fund_flow=FundFlowSnapshot(
            symbol="000001",
            name="test",
            timestamp=timestamp,
            super_large_net_inflow=1_000_000,
            large_net_inflow=1_000_000,
            medium_net_inflow=0,
            small_net_inflow=-500_000,
            main_net_inflow_pct=8.0,
            change_pct=3.0,
            amount=100_000_000,
            turnover_rate=8.0,
            provider="test",
            period="daily",
        ),
        intent_profile=MainForceProfile(
            trade_date=date(2026, 1, 1),
            close=10.0,
            daily_trend="up",
            weekly_trend="up",
            monthly_trend="up",
            stage="markup_confirmed",
            vwap_60=9.5,
            vwap_120=9.0,
            close_vs_vwap_60_pct=5.0,
            close_vs_vwap_120_pct=11.0,
            turnover_20=60,
            turnover_60=120,
            main_flow_3=3_000_000,
            main_flow_5=5_000_000,
            main_flow_10=10_000_000,
            obv_slope_20=0.2,
            adl_slope_20=0.2,
            accumulation_score=accumulation_score,
            markup_score=70,
            distribution_score=20,
        ),
    )
