from datetime import date, datetime

from wealth_lab.diagnostics import diagnose_replay
from wealth_lab.models import (
    Bar,
    Fill,
    FundFlowSnapshot,
    FundSignal,
    OrderSide,
    PatternTag,
    PortfolioSnapshot,
    Quote,
    StockSignal,
)
from wealth_lab.replay import ReplayDecision, ReplayResult


def test_diagnostics_explains_entry_detection_from_signal_day() -> None:
    signal_date = date(2026, 1, 1)
    entry_date = date(2026, 1, 2)
    exit_date = date(2026, 1, 3)
    result = ReplayResult(
        symbol="000001",
        name="test",
        bars_count=3,
        fund_flows_count=3,
        first_bar_date=signal_date,
        last_bar_date=exit_date,
        signals=[_signal(signal_date)],
        decisions=[
            ReplayDecision(
                signal_date=signal_date,
                symbol="000001",
                fund_signal="买入",
                pattern_tags=("放量突破",),
                side="BUY",
                reason="breakout_entry: 买入; 放量突破",
            )
        ],
        fills=[
            Fill("000001", OrderSide.BUY, 1000, 10.0, entry_date, 10000, 0, "breakout_entry: 买入; 放量突破"),
            Fill("000001", OrderSide.SELL, 1000, 10.5, exit_date, 10500, 0, "exit: 卖出; 突破失败"),
        ],
        equity_curve=[PortfolioSnapshot(exit_date, 100500, 0, 100500, {})],
        missing_fund_flow_dates=[],
        skipped_orders=[],
        initial_cash=100000,
        final_value=100500,
        total_return=0.005,
        max_drawdown=0,
        bars=[
            _bar(signal_date, 10.0, volume=1_000_000, change_pct=1.0),
            _bar(entry_date, 10.3, volume=1_800_000, change_pct=3.0),
            _bar(exit_date, 10.5, volume=1_600_000, change_pct=1.9),
        ],
    )

    diagnostics = diagnose_replay(result)

    assert diagnostics.entries[0].signal_date == signal_date
    assert diagnostics.entries[0].entry_family == "breakout_entry"
    assert "main_pct=8.00%" in diagnostics.entries[0].detection
    assert diagnostics.family_summaries[0].avg_return_pct == 5.0
    story = diagnostics.trade_stories[0]
    assert story.thesis.entry_family == "breakout_entry"
    assert story.thesis.buy_type == "breakout_start"
    assert story.thesis.vpa_archetype == "effort_vs_result_breakout"
    assert story.thesis.expected_holding_days == "3-5 bars"
    assert story.confirmations >= 1
    assert story.verdict == "thesis_confirmed"
    assert "close_above_entry" in story.holding_evidence
    review = diagnostics.position_action_reviews[0]
    assert review.gap_pct == 3.0
    assert review.gap_bucket == 3
    assert review.opening_classification == "neutral_open"
    assert review.position_action == "buy_50"
    hypotheses = diagnostics.knowledge_hypothesis_reviews
    assert {item.lens for item in hypotheses} == {
        "volume_price",
        "pattern_structure",
        "opening_attention",
        "support_risk",
        "invalidation",
    }
    assert hypotheses[0].source_id == "coulling_wyckoff_weis"
    assert hypotheses[0].bucket == "effort_vs_result_breakout"
    assert hypotheses[0].diagnostic_status == "CONFIRMED_OBSERVATION"


def test_position_action_review_parses_opening_class_and_support() -> None:
    signal_date = date(2026, 1, 1)
    entry_date = date(2026, 1, 2)
    exit_date = date(2026, 1, 3)
    entry_reason = "volume_price_trial_entry: class=expected_open support=9.80"
    result = ReplayResult(
        symbol="000001",
        name="test",
        bars_count=3,
        fund_flows_count=0,
        first_bar_date=signal_date,
        last_bar_date=exit_date,
        signals=[],
        decisions=[
            ReplayDecision(
                signal_date=signal_date,
                symbol="000001",
                fund_signal="volume_price",
                pattern_tags=("quiet_consolidation",),
                side="BUY",
                reason=entry_reason,
            )
        ],
        fills=[
            Fill("000001", OrderSide.BUY, 1000, 10.0, entry_date, 10000, 0, entry_reason),
            Fill("000001", OrderSide.SELL, 1000, 10.4, exit_date, 10400, 0, "exit: scheduled"),
        ],
        equity_curve=[PortfolioSnapshot(exit_date, 100400, 0, 100400, {})],
        missing_fund_flow_dates=[],
        skipped_orders=[],
        initial_cash=100000,
        final_value=100400,
        total_return=0.004,
        max_drawdown=0,
        bars=[
            _bar(signal_date, 10.0, volume=1_000_000, change_pct=0.0),
            _bar(entry_date, 10.2, volume=1_000_000, change_pct=2.0),
            _bar(exit_date, 10.4, volume=900_000, change_pct=2.0),
        ],
    )

    review = diagnose_replay(result).position_action_reviews[0]

    assert review.gap_pct == 2.0
    assert review.gap_bucket == 2
    assert review.opening_classification == "expected_open"
    assert review.support_distance_pct == 3.9216
    assert review.position_action == "buy_50"
    assert review.action_reason == "confirmed_thesis_with_usable_support"


def test_position_action_review_observes_when_signal_bar_is_missing() -> None:
    signal_date = date(2026, 1, 1)
    entry_date = date(2026, 1, 2)
    exit_date = date(2026, 1, 3)
    entry_reason = "volume_price_trial_entry: support=9.70"
    result = ReplayResult(
        symbol="000001",
        name="test",
        bars_count=2,
        fund_flows_count=0,
        first_bar_date=entry_date,
        last_bar_date=exit_date,
        signals=[],
        decisions=[
            ReplayDecision(
                signal_date=signal_date,
                symbol="000001",
                fund_signal="volume_price",
                pattern_tags=("quiet_consolidation",),
                side="BUY",
                reason=entry_reason,
            )
        ],
        fills=[
            Fill("000001", OrderSide.BUY, 1000, 10.0, entry_date, 10000, 0, entry_reason),
            Fill("000001", OrderSide.SELL, 1000, 10.2, exit_date, 10200, 0, "exit: scheduled"),
        ],
        equity_curve=[PortfolioSnapshot(exit_date, 100200, 0, 100200, {})],
        missing_fund_flow_dates=[],
        skipped_orders=[],
        initial_cash=100000,
        final_value=100200,
        total_return=0.002,
        max_drawdown=0,
        bars=[
            _bar(entry_date, 10.0, volume=1_000_000, change_pct=0.0),
            _bar(exit_date, 10.2, volume=900_000, change_pct=2.0),
        ],
    )

    review = diagnose_replay(result).position_action_reviews[0]

    assert review.gap_pct is None
    assert review.gap_bucket is None
    assert review.opening_classification == "insufficient_opening_history"
    assert review.position_action == "observe"
    assert review.action_reason == "insufficient_opening_history"


def _signal(trade_date: date) -> StockSignal:
    timestamp = datetime.combine(trade_date, datetime.min.time())
    return StockSignal(
        symbol="000001",
        name="test",
        timestamp=timestamp,
        fund_signal=FundSignal.BUY,
        pattern_tags=(PatternTag.VOLUME_BREAKOUT,),
        anomalies=(),
        score=90,
        reasons=(),
        quote=Quote(
            symbol="000001",
            name="test",
            price=10.0,
            change_pct=3.0,
            timestamp=timestamp,
            provider="test",
            volume_ratio=2.0,
        ),
        fund_flow=FundFlowSnapshot(
            symbol="000001",
            name="test",
            timestamp=timestamp,
            super_large_net_inflow=1_000_000,
            large_net_inflow=500_000,
            medium_net_inflow=0,
            small_net_inflow=-300_000,
            main_net_inflow_pct=8.0,
            change_pct=3.0,
            amount=100_000_000,
            turnover_rate=5.0,
            provider="test",
            period="daily",
        ),
    )


def _bar(
    trade_date: date,
    close: float,
    volume: int,
    change_pct: float,
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
        change_pct=change_pct,
        turnover_rate=5.0,
    )
