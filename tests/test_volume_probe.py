from datetime import date, datetime, timedelta

from wealth_lab.models import Bar, FundFlowSnapshot, MainForceProfile, Order, OrderSide
from wealth_lab.paper import PaperBroker
from wealth_lab.replay import HistoricalReplayRunner
from wealth_lab.trade_discipline import (
    DisciplineConfig,
    TradeDecision,
    TradeDiscipline,
    discipline_config_for_mode,
)
from wealth_lab.volume_probe import (
    OpeningExpectationConfig,
    VolumeProbeContext,
    VolumeProbeConfig,
    VolumePriceNode,
    build_volume_probe_opening_expectation,
    build_point_in_time_volume_probe_context,
)


def test_volume_probe_uses_only_prior_resolved_same_node_cases() -> None:
    bars: list[Bar] = []
    start = date(2026, 1, 1)
    _append_base(bars, start)
    _append_positive_shrink_case(bars, start)
    _append_base(bars, start)
    current_index = len(bars)
    bars.append(_shrink_bar(start + timedelta(days=current_index), 10.18))
    config = VolumeProbeConfig(
        window=3,
        min_cases=2,
        min_win_rate_pct=50.0,
        min_avg_return_pct=0.10,
    )

    context = build_point_in_time_volume_probe_context(bars, current_index, config)

    assert context.node.node_type == "shrink_pullback"
    assert context.resolved_cases == 1
    assert not context.passed
    assert context.reason == "insufficient_cases:1/2"


def test_volume_probe_breakout_only_config_blocks_failed_clusters() -> None:
    bars: list[Bar] = []
    start = date(2026, 1, 1)
    _append_base(bars, start)
    _append_positive_shrink_case(bars, start)
    _append_base(bars, start)
    current_index = len(bars)
    bars.append(_shrink_bar(start + timedelta(days=current_index), 10.18))
    config = VolumeProbeConfig(
        window=3,
        min_cases=0,
        min_win_rate_pct=0.0,
        min_avg_return_pct=-100.0,
        allowed_node_types=("volume_breakout",),
    )

    context = build_point_in_time_volume_probe_context(bars, current_index, config)

    assert context.node.node_type == "shrink_pullback"
    assert not context.passed
    assert context.reason == "node_not_allowed:shrink_pullback"

    quiet_bars: list[Bar] = []
    _append_base(quiet_bars, start)
    quiet_index = len(quiet_bars)
    quiet_bars.append(_quiet_bar(start + timedelta(days=quiet_index), 10.00))

    quiet_context = build_point_in_time_volume_probe_context(
        quiet_bars,
        quiet_index,
        config,
    )

    assert quiet_context.node.node_type == "quiet_consolidation"
    assert not quiet_context.passed
    assert quiet_context.reason == "node_not_allowed:quiet_consolidation"


def test_volume_probe_replay_trades_without_fund_flow_rows() -> None:
    bars: list[Bar] = []
    start = date(2026, 1, 1)
    _append_base(bars, start)
    _append_positive_shrink_case(bars, start)
    _append_base(bars, start)
    _append_positive_shrink_case(bars, start)
    _append_base(bars, start)
    signal_index = len(bars)
    bars.append(_shrink_bar(start + timedelta(days=signal_index), 10.16))
    bars.append(_bar(start + timedelta(days=len(bars)), open_price=10.10, close=10.20))
    bars.append(_bar(start + timedelta(days=len(bars)), open_price=10.45, close=10.50))
    discipline = TradeDiscipline(
        DisciplineConfig(
            enable_signal_entries=False,
            enable_pursuit_probe=False,
            enable_confirmation_add=False,
            enable_volume_price_probe=True,
            volume_price_probe_weight=0.10,
            volume_price_probe_window=3,
            volume_price_probe_min_cases=2,
            volume_price_probe_min_win_rate_pct=50.0,
            volume_price_probe_min_avg_return_pct=0.10,
        )
    )

    result = HistoricalReplayRunner(
        bars=bars,
        fund_flows=[],
        initial_cash=100000,
        discipline=discipline,
    ).run()

    volume_buys = [
        item for item in result.decisions
        if item.reason.startswith("volume_price_trial_entry")
    ]
    assert len(result.signals) == 0
    assert len(result.missing_fund_flow_dates) == len(bars)
    assert len(volume_buys) == 1
    assert len(result.fills) == 2
    assert result.fills[0].side == OrderSide.BUY
    assert result.fills[0].trade_date == bars[signal_index + 1].trade_date
    assert result.fills[1].side == OrderSide.SELL
    assert result.fills[1].trade_date == bars[signal_index + 2].trade_date


def test_volume_probe_follow_through_exit_sells_next_open_after_invalidation() -> None:
    bars = _follow_through_bars(
        closes=(10.00, 10.10, 9.70),
        changes=(0.0, 1.0, -3.5),
    )
    broker = _broker_with_volume_buy(bars[1], reason_support=9.80, execute_price=10.00)
    discipline = _follow_through_discipline()

    decision = discipline.decide_volume_probe_exit(
        "000001",
        broker,
        bars=bars,
        current_index=2,
    )

    assert decision.side == OrderSide.SELL
    assert "volume_price_follow_through_exit: invalidated" in decision.reason
    assert "invalidations=1" in decision.reason


def test_volume_probe_follow_through_exit_sells_after_three_bars_without_confirm() -> None:
    bars = _follow_through_bars(
        closes=(10.00, 10.00, 10.00, 10.00),
        changes=(0.0, 0.0, 0.0, 0.0),
    )
    broker = _broker_with_volume_buy(bars[1], reason_support=9.80, execute_price=10.00)
    discipline = _follow_through_discipline()

    decision = discipline.decide_volume_probe_exit(
        "000001",
        broker,
        bars=bars,
        current_index=3,
    )

    assert decision.side == OrderSide.SELL
    assert "volume_price_follow_through_exit: no_follow_through" in decision.reason
    assert "hold_bars=3" in decision.reason
    assert "confirmations=0 warnings=0" in decision.reason


def test_volume_probe_follow_through_exit_holds_profitable_first_bar_when_required() -> None:
    bars = _follow_through_bars(
        closes=(10.00, 10.20),
        changes=(0.0, 1.0),
    )
    broker = _broker_with_volume_buy(bars[1], reason_support=9.80)
    discipline = TradeDiscipline(
        DisciplineConfig(
            enable_signal_entries=False,
            enable_pursuit_probe=False,
            enable_confirmation_add=False,
            enable_volume_price_probe=True,
            enable_volume_price_follow_through_exit=True,
            volume_price_follow_through_no_confirm_bars=1,
            volume_price_follow_through_max_hold_bars=5,
            volume_price_follow_through_first_bar_exit_requires_loss=True,
        )
    )

    decision = discipline.decide_volume_probe_exit(
        "000001",
        broker,
        bars=bars,
        current_index=1,
    )

    assert decision.side is None
    assert "first_bar_profitable_trial" in decision.reason


def test_volume_probe_follow_through_exit_sells_losing_first_bar_when_required() -> None:
    bars = _follow_through_bars(
        closes=(10.00, 9.90),
        changes=(0.0, -1.0),
    )
    broker = _broker_with_volume_buy(bars[1], reason_support=9.80)
    discipline = TradeDiscipline(
        DisciplineConfig(
            enable_signal_entries=False,
            enable_pursuit_probe=False,
            enable_confirmation_add=False,
            enable_volume_price_probe=True,
            enable_volume_price_follow_through_exit=True,
            volume_price_follow_through_no_confirm_bars=1,
            volume_price_follow_through_max_hold_bars=5,
            volume_price_follow_through_first_bar_exit_requires_loss=True,
        )
    )

    decision = discipline.decide_volume_probe_exit(
        "000001",
        broker,
        bars=bars,
        current_index=1,
    )

    assert decision.side == OrderSide.SELL
    assert "volume_price_follow_through_exit: no_follow_through" in decision.reason


def test_volume_probe_follow_through_exit_holds_confirmed_trial_before_max() -> None:
    bars = _follow_through_bars(
        closes=(10.00, 10.15, 10.30, 10.45),
        changes=(0.0, 1.5, 1.2, 1.0),
    )
    broker = _broker_with_volume_buy(bars[1], reason_support=9.80)
    discipline = _follow_through_discipline()

    decision = discipline.decide_volume_probe_exit(
        "000001",
        broker,
        bars=bars,
        current_index=3,
    )

    assert decision.side is None
    assert decision.reason.startswith("volume_price_follow_through_hold")
    assert "confirmations=2" in decision.reason


def test_volume_probe_follow_through_exit_sells_confirmed_trial_at_max_hold() -> None:
    bars = _follow_through_bars(
        closes=(10.00, 10.15, 10.25, 10.35, 10.45, 10.55),
        changes=(0.0, 1.5, 1.0, 1.0, 0.8, 0.8),
    )
    broker = _broker_with_volume_buy(bars[1], reason_support=9.80)
    discipline = _follow_through_discipline()

    decision = discipline.decide_volume_probe_exit(
        "000001",
        broker,
        bars=bars,
        current_index=5,
    )

    assert decision.side == OrderSide.SELL
    assert "volume_price_follow_through_exit: max_hold" in decision.reason
    assert "hold_bars=5" in decision.reason
    assert "confirmations=4" in decision.reason


def test_main_force_profile_filter_allows_accumulation_inflow_breakout() -> None:
    discipline = TradeDiscipline(
        DisciplineConfig(
            enable_volume_price_probe=True,
            volume_price_probe_allowed_node_types=("volume_breakout",),
            enable_volume_price_main_force_profile_filter=True,
        )
    )

    decision = discipline.decide_volume_probe(
        "000001",
        _passed_volume_context("volume_breakout"),
        PaperBroker(initial_cash=100000),
        intent_profile=_profile(
            stage="accumulation_watch",
            weekly_trend="up",
            close_vs_vwap60=1.0,
            main_flow_5=1_000_000,
            main_flow_10=2_000_000,
            distribution_score=35.0,
        ),
    )

    assert decision.side == OrderSide.BUY
    assert decision.reason.startswith("volume_price_trial_entry")


def test_main_force_profile_filter_blocks_distribution_or_negative_flow() -> None:
    discipline = TradeDiscipline(
        DisciplineConfig(
            enable_volume_price_probe=True,
            volume_price_probe_allowed_node_types=("volume_breakout",),
            enable_volume_price_main_force_profile_filter=True,
        )
    )

    distribution_decision = discipline.decide_volume_probe(
        "000001",
        _passed_volume_context("volume_breakout"),
        PaperBroker(initial_cash=100000),
        intent_profile=_profile(
            stage="distribution_risk",
            weekly_trend="up",
            close_vs_vwap60=1.0,
            main_flow_5=1_000_000,
            main_flow_10=2_000_000,
            distribution_score=35.0,
        ),
    )
    weak_flow_decision = discipline.decide_volume_probe(
        "000001",
        _passed_volume_context("volume_breakout"),
        PaperBroker(initial_cash=100000),
        intent_profile=_profile(
            stage="accumulation_watch",
            weekly_trend="up",
            close_vs_vwap60=1.0,
            main_flow_5=-1_000_000,
            main_flow_10=-2_000_000,
            distribution_score=35.0,
        ),
    )

    assert distribution_decision.side is None
    assert "main_force_profile_filter_stage" in distribution_decision.reason
    assert weak_flow_decision.side is None
    assert "main_force_profile_filter_flow_not_positive" in weak_flow_decision.reason


def test_weak_main_force_block_blocks_only_clear_distribution_or_weak_flow() -> None:
    discipline = TradeDiscipline(
        DisciplineConfig(
            enable_volume_price_probe=True,
            volume_price_probe_allowed_node_types=("volume_breakout",),
            enable_volume_price_weak_main_force_block=True,
        )
    )

    accumulation_decision = discipline.decide_volume_probe(
        "000001",
        _passed_volume_context("volume_breakout"),
        PaperBroker(initial_cash=100000),
        intent_profile=_profile(
            stage="accumulation_watch",
            weekly_trend="up",
            close_vs_vwap60=1.0,
            main_flow_3=-1_000_000,
            main_flow_5=1_000_000,
            main_flow_10=2_000_000,
            distribution_score=35.0,
        ),
    )
    failed_breakout_decision = discipline.decide_volume_probe(
        "000001",
        _passed_volume_context("volume_breakout"),
        PaperBroker(initial_cash=100000),
        intent_profile=_profile(
            stage="failed_breakout",
            weekly_trend="up",
            close_vs_vwap60=1.0,
            main_flow_3=1_000_000,
            main_flow_5=1_000_000,
            main_flow_10=2_000_000,
            distribution_score=35.0,
        ),
    )
    weak_flow_decision = discipline.decide_volume_probe(
        "000001",
        _passed_volume_context("volume_breakout"),
        PaperBroker(initial_cash=100000),
        intent_profile=_profile(
            stage="markup_confirmed",
            weekly_trend="up",
            close_vs_vwap60=1.0,
            main_flow_3=-1_000_000,
            main_flow_5=-1_000_000,
            main_flow_10=2_000_000,
            distribution_score=35.0,
        ),
    )

    assert accumulation_decision.side == OrderSide.BUY
    assert failed_breakout_decision.side is None
    assert "weak_main_force_block_stage" in failed_breakout_decision.reason
    assert weak_flow_decision.side is None
    assert "weak_main_force_block_negative_flow" in weak_flow_decision.reason


def test_volume_probe_opening_gate_cancels_high_open_above_expected_range() -> None:
    bars: list[Bar] = []
    start = date(2026, 1, 1)
    _append_base(bars, start)
    _append_positive_shrink_case(bars, start)
    _append_base(bars, start)
    _append_positive_shrink_case(bars, start)
    _append_base(bars, start)
    signal_index = len(bars)
    bars.append(_shrink_bar(start + timedelta(days=signal_index), 10.00))
    bars.append(_bar(start + timedelta(days=len(bars)), open_price=10.50, close=10.30))
    bars.append(_bar(start + timedelta(days=len(bars)), open_price=10.20, close=10.25))

    result = HistoricalReplayRunner(
        bars=bars,
        fund_flows=[],
        initial_cash=100000,
        discipline=_volume_probe_discipline(),
    ).run()

    assert not result.fills
    assert any(
        "opening_above_expected_range" in item
        and "expected=" in item
        and "range=" in item
        for item in result.skipped_orders
    )


def test_volume_probe_opening_gate_allows_high_open_when_history_expects_it() -> None:
    bars: list[Bar] = []
    start = date(2026, 1, 1)
    _append_base(bars, start)
    _append_positive_shrink_case(bars, start, entry_gap_pct=3.4)
    _append_base(bars, start)
    _append_positive_shrink_case(bars, start, entry_gap_pct=3.6)
    _append_base(bars, start)
    signal_index = len(bars)
    bars.append(_shrink_bar(start + timedelta(days=signal_index), 10.16))
    bars.append(_bar(start + timedelta(days=len(bars)), open_price=10.50, close=10.70))
    bars.append(_bar(start + timedelta(days=len(bars)), open_price=10.80, close=10.85))

    result = HistoricalReplayRunner(
        bars=bars,
        fund_flows=[],
        initial_cash=100000,
        discipline=_volume_probe_discipline(),
    ).run()

    assert result.fills[0].side == OrderSide.BUY
    assert "volume_price_opening_confirmed" in result.fills[0].reason


def test_volume_probe_opening_gate_cancels_pullback_chase_premium() -> None:
    bars: list[Bar] = []
    start = date(2026, 1, 1)
    _append_base(bars, start)
    _append_positive_shrink_case(bars, start, entry_gap_pct=-1.0)
    _append_base(bars, start)
    _append_positive_shrink_case(bars, start, entry_gap_pct=4.0)
    _append_base(bars, start)
    signal_index = len(bars)
    bars.append(_shrink_bar(start + timedelta(days=signal_index), 10.00))
    bars.append(_bar(start + timedelta(days=len(bars)), open_price=10.32, close=10.10))
    bars.append(_bar(start + timedelta(days=len(bars)), open_price=10.05, close=10.00))

    result = HistoricalReplayRunner(
        bars=bars,
        fund_flows=[],
        initial_cash=100000,
        discipline=_volume_probe_discipline(),
    ).run()

    assert not result.fills
    assert any(
        "opening_above_expected_pullback_premium" in item
        for item in result.skipped_orders
    )


def test_volume_probe_opening_gate_cancels_breakout_low_open_below_expected_range() -> None:
    bars: list[Bar] = []
    start = date(2026, 1, 1)
    _append_breakout_base(bars, start)
    _append_positive_breakout_case(bars, start, change_pct=4.0, entry_gap_pct=1.2)
    _append_breakout_base(bars, start)
    _append_positive_breakout_case(bars, start, change_pct=4.5, entry_gap_pct=1.1)
    _append_breakout_base(bars, start)
    signal_index = len(bars)
    bars.append(_breakout_bar(start + timedelta(days=signal_index), 11.10, change_pct=9.0))
    bars.append(_bar(start + timedelta(days=len(bars)), open_price=11.00, close=10.80))
    bars.append(_bar(start + timedelta(days=len(bars)), open_price=10.70, close=10.75))

    result = HistoricalReplayRunner(
        bars=bars,
        fund_flows=[],
        initial_cash=100000,
        discipline=_volume_probe_discipline(),
    ).run()

    assert not result.fills
    assert any(
        "opening_below_expected_range_after_breakout" in item
        for item in result.skipped_orders
    )


def test_volume_probe_opening_gate_cancels_breakout_flat_open_with_wide_support() -> None:
    bars: list[Bar] = []
    start = date(2026, 1, 1)
    _append_breakout_base(bars, start)
    _append_positive_breakout_case(bars, start, change_pct=4.0, entry_gap_pct=1.2)
    _append_breakout_base(bars, start)
    _append_positive_breakout_case(bars, start, change_pct=4.5, entry_gap_pct=1.1)
    _append_breakout_base(bars, start)
    signal_index = len(bars)
    bars.append(
        _breakout_bar_with_low(
            start + timedelta(days=signal_index),
            11.10,
            change_pct=4.0,
            low=10.00,
        )
    )
    bars.append(_bar(start + timedelta(days=len(bars)), open_price=11.10, close=10.95))

    confirmed = TradeDiscipline(
        DisciplineConfig(
            enable_volume_price_probe=True,
            volume_price_probe_window=3,
            volume_price_probe_min_cases=2,
            volume_price_probe_min_win_rate_pct=50.0,
            volume_price_probe_min_avg_return_pct=0.10,
            volume_price_breakout_wide_support_distance_pct=8.0,
            volume_price_breakout_min_gap_for_wide_support_pct=0.5,
        )
    ).confirm_volume_probe_opening(
        decision=TradeDecision(
            side=OrderSide.BUY,
            reason="volume_price_trial_entry: node=volume_breakout",
            target_weight=0.06,
        ),
        bars=bars,
        signal_index=signal_index,
        execution_index=signal_index + 1,
    )

    assert confirmed.side is None
    assert "breakout_wide_support_without_opening_demand" in confirmed.reason


def test_volume_probe_opening_gate_cancels_breakout_overheated_gap() -> None:
    bars: list[Bar] = []
    start = date(2026, 1, 1)
    _append_breakout_base(bars, start)
    _append_positive_breakout_case(bars, start, change_pct=4.0, entry_gap_pct=3.4)
    _append_breakout_base(bars, start)
    _append_positive_breakout_case(bars, start, change_pct=4.5, entry_gap_pct=3.6)
    _append_breakout_base(bars, start)
    signal_index = len(bars)
    bars.append(
        _breakout_bar_with_low(
            start + timedelta(days=signal_index),
            11.10,
            change_pct=4.0,
            low=10.60,
        )
    )
    bars.append(_bar(start + timedelta(days=len(bars)), open_price=11.45, close=11.20))

    confirmed = TradeDiscipline(
        DisciplineConfig(
            enable_volume_price_probe=True,
            volume_price_probe_window=3,
            volume_price_probe_min_cases=2,
            volume_price_probe_min_win_rate_pct=50.0,
            volume_price_probe_min_avg_return_pct=0.10,
            volume_price_breakout_max_opening_gap_pct=3.0,
        )
    ).confirm_volume_probe_opening(
        decision=TradeDecision(
            side=OrderSide.BUY,
            reason="volume_price_trial_entry: node=volume_breakout",
            target_weight=0.06,
        ),
        bars=bars,
        signal_index=signal_index,
        execution_index=signal_index + 1,
    )

    assert confirmed.side is None
    assert "breakout_opening_gap_too_high" in confirmed.reason


def test_breakout_confirmation_entry_waits_for_next_day_confirmation_before_buying() -> None:
    bars, flows, signal_index = _breakout_confirmation_dataset(
        confirm_close=10.72,
        confirm_main_flow=800_000.0,
    )

    result = HistoricalReplayRunner(
        bars=bars,
        fund_flows=flows,
        initial_cash=100000,
        discipline=_breakout_confirmation_discipline(),
    ).run()

    signal_decision = next(
        item
        for item in result.decisions
        if item.observation_type == "volume_price"
        and item.signal_date == bars[signal_index].trade_date
    )
    buy_fills = [item for item in result.fills if item.side == OrderSide.BUY]

    assert signal_decision.volume_node == "volume_breakout"
    assert signal_decision.side is None
    assert [item.trade_date for item in buy_fills] == [
        bars[signal_index + 2].trade_date
    ]
    assert "breakout_confirmation" in buy_fills[0].reason


def test_breakout_confirmation_entry_cancels_when_confirmation_fails() -> None:
    bars, flows, _signal_index = _breakout_confirmation_dataset(
        confirm_close=10.44,
        confirm_low=10.24,
        confirm_main_flow=-800_000.0,
    )

    result = HistoricalReplayRunner(
        bars=bars,
        fund_flows=flows,
        initial_cash=100000,
        discipline=_breakout_confirmation_discipline(),
    ).run()

    assert not [item for item in result.fills if item.side == OrderSide.BUY]


def test_pre_breakout_watchlist_buys_after_confirmed_breakout() -> None:
    bars, flows, watch_index, confirmation_index = _pre_breakout_watch_dataset(
        confirmation_main_flow=800_000.0,
    )

    result = HistoricalReplayRunner(
        bars=bars,
        fund_flows=flows,
        initial_cash=100000,
        discipline=_pre_breakout_watchlist_discipline(),
    ).run()

    watch_records = [
        item for item in result.decisions
        if item.reason.startswith("volume_price_pre_breakout_watch:")
    ]
    handoff_records = [
        item for item in result.decisions
        if "pre_breakout_watchlist_entry" in item.reason
    ]
    buy_fills = [item for item in result.fills if item.side == OrderSide.BUY]

    assert watch_records
    assert watch_records[0].signal_date <= bars[watch_index].trade_date
    assert handoff_records
    assert handoff_records[0].signal_date == bars[confirmation_index].trade_date
    assert handoff_records[0].side == "BUY"
    assert [item.trade_date for item in buy_fills] == [
        bars[confirmation_index + 1].trade_date
    ]
    assert "watch_node=" in buy_fills[0].reason
    assert "tier=continuous_confirmation" in buy_fills[0].reason


def test_pre_breakout_watchlist_cancels_when_main_flow_turns_weak() -> None:
    bars, flows, _watch_index, _confirmation_index = _pre_breakout_watch_dataset(
        confirmation_main_flow=-800_000.0,
    )

    result = HistoricalReplayRunner(
        bars=bars,
        fund_flows=flows,
        initial_cash=100000,
        discipline=_pre_breakout_watchlist_discipline(),
    ).run()

    assert not [item for item in result.fills if item.side == OrderSide.BUY]
    assert any("main_flow_weak" in item.reason for item in result.decisions)


def test_follow_through_exit_sells_when_main_flow_turns_negative() -> None:
    bars = _follow_through_bars(
        closes=(10.00, 10.15),
        changes=(0.0, 1.5),
    )
    broker = _broker_with_volume_buy(bars[1], reason_support=9.80)
    discipline = TradeDiscipline(
        DisciplineConfig(
            enable_signal_entries=False,
            enable_pursuit_probe=False,
            enable_confirmation_add=False,
            enable_volume_price_probe=True,
            enable_volume_price_follow_through_exit=True,
            volume_price_follow_through_exit_on_negative_main_flow=True,
        )
    )

    decision = discipline.decide_volume_probe_exit(
        "000001",
        broker,
        bars=bars,
        current_index=1,
        main_flow=-1.0,
    )

    assert decision.side == OrderSide.SELL
    assert "main_flow_weak" in decision.reason


def test_volume_probe_opening_gate_allows_moderate_low_open() -> None:
    bars: list[Bar] = []
    start = date(2026, 1, 1)
    _append_base(bars, start)
    _append_positive_shrink_case(bars, start)
    _append_base(bars, start)
    _append_positive_shrink_case(bars, start)
    _append_base(bars, start)
    signal_index = len(bars)
    bars.append(_shrink_bar(start + timedelta(days=signal_index), 10.16))
    bars.append(_bar(start + timedelta(days=len(bars)), open_price=10.10, close=10.20))
    bars.append(_bar(start + timedelta(days=len(bars)), open_price=10.45, close=10.50))

    result = HistoricalReplayRunner(
        bars=bars,
        fund_flows=[],
        initial_cash=100000,
        discipline=_volume_probe_discipline(),
    ).run()

    assert result.fills[0].side == OrderSide.BUY


def test_volume_probe_risk_sizing_caps_low_support_distance() -> None:
    bars: list[Bar] = []
    start = date(2026, 1, 1)
    _append_base(bars, start)
    _append_positive_shrink_case(bars, start)
    _append_base(bars, start)
    _append_positive_shrink_case(bars, start)
    _append_base(bars, start)
    signal_index = len(bars)
    bars.append(_shrink_bar(start + timedelta(days=signal_index), 10.16))
    bars.append(_bar(start + timedelta(days=len(bars)), open_price=10.10, close=10.20))

    confirmed = _risk_sizing_discipline().confirm_volume_probe_opening(
        decision=TradeDecision(
            side=OrderSide.BUY,
            reason="volume_price_trial_entry: node=shrink_pullback",
            target_weight=0.06,
        ),
        bars=bars,
        signal_index=signal_index,
        execution_index=signal_index + 1,
    )

    assert confirmed.side == OrderSide.BUY
    assert confirmed.target_weight == 0.12
    assert "volume_price_risk_sized" in confirmed.reason
    assert "weight=12.00%" in confirmed.reason


def test_volume_probe_risk_sizing_can_respect_tiered_decision_cap() -> None:
    bars: list[Bar] = []
    start = date(2026, 1, 1)
    _append_base(bars, start)
    _append_positive_shrink_case(bars, start)
    _append_base(bars, start)
    _append_positive_shrink_case(bars, start)
    _append_base(bars, start)
    signal_index = len(bars)
    bars.append(_shrink_bar(start + timedelta(days=signal_index), 10.16))
    bars.append(_bar(start + timedelta(days=len(bars)), open_price=10.10, close=10.20))
    discipline = TradeDiscipline(
        DisciplineConfig(
            enable_volume_price_probe=True,
            volume_price_probe_min_cases=2,
            enable_volume_price_risk_sizing=True,
            volume_price_account_risk_pct=0.003,
            volume_price_risk_sizing_max_weight=0.20,
            volume_price_risk_sizing_respects_decision_cap=True,
            volume_price_min_stop_distance_pct=0.015,
        )
    )

    confirmed = discipline.confirm_volume_probe_opening(
        decision=TradeDecision(
            side=OrderSide.BUY,
            reason="volume_price_trial_entry: node=shrink_pullback",
            target_weight=0.05,
        ),
        bars=bars,
        signal_index=signal_index,
        execution_index=signal_index + 1,
    )

    assert confirmed.side == OrderSide.BUY
    assert confirmed.target_weight == 0.05
    assert "weight=5.00%" in confirmed.reason


def test_volume_probe_risk_sizing_reduces_wide_support_distance() -> None:
    bars: list[Bar] = []
    start = date(2026, 1, 1)
    _append_base(bars, start)
    _append_positive_shrink_case(bars, start)
    _append_base(bars, start)
    _append_positive_shrink_case(bars, start)
    _append_base(bars, start)
    signal_index = len(bars)
    bars.append(
        Bar(
            symbol="000001",
            trade_date=start + timedelta(days=signal_index),
            open=10.21,
            high=10.24,
            low=9.00,
            close=10.16,
            volume=500,
            amount=10.16 * 500,
            change_pct=-0.5,
            turnover_rate=2.0,
        )
    )
    bars.append(_bar(start + timedelta(days=len(bars)), open_price=10.10, close=10.20))

    confirmed = _risk_sizing_discipline().confirm_volume_probe_opening(
        decision=TradeDecision(
            side=OrderSide.BUY,
            reason="volume_price_trial_entry: node=shrink_pullback",
            target_weight=0.06,
        ),
        bars=bars,
        signal_index=signal_index,
        execution_index=signal_index + 1,
    )

    assert confirmed.side == OrderSide.BUY
    assert confirmed.target_weight < 0.06
    assert "raw_stop=10.89%" in confirmed.reason


def test_volume_probe_support_quality_blocks_dry_up_without_main_flow() -> None:
    discipline = TradeDiscipline(
        DisciplineConfig(
            enable_volume_price_probe=True,
            enable_volume_price_support_quality_filter=True,
            volume_price_block_dry_up_without_main_flow=True,
        )
    )
    context = _passed_volume_context("dry_up_base")
    profile = _profile(
        stage="neutral",
        weekly_trend="base_down",
        close_vs_vwap60=-2.0,
        main_flow_5=None,
    )

    decision = discipline.decide_volume_probe(
        "000001",
        context,
        PaperBroker(100000),
        intent_profile=profile,
    )

    assert decision.side is None
    assert "support_quality_dry_up_missing_or_negative_main_flow" in decision.reason


def test_volume_probe_support_quality_allows_dry_up_with_main_flow() -> None:
    discipline = TradeDiscipline(
        DisciplineConfig(
            enable_volume_price_probe=True,
            enable_volume_price_support_quality_filter=True,
            volume_price_block_dry_up_without_main_flow=True,
        )
    )
    context = _passed_volume_context("dry_up_base")
    profile = _profile(
        stage="neutral",
        weekly_trend="base_down",
        close_vs_vwap60=-2.0,
        main_flow_5=1_000_000.0,
    )

    decision = discipline.decide_volume_probe(
        "000001",
        context,
        PaperBroker(100000),
        intent_profile=profile,
    )

    assert decision.side == OrderSide.BUY


def test_volume_probe_support_quality_blocks_low_edge_dry_up() -> None:
    discipline = TradeDiscipline(
        DisciplineConfig(
            enable_volume_price_probe=True,
            enable_volume_price_support_quality_filter=True,
            volume_price_support_quality_min_dry_up_avg_return_pct=0.50,
        )
    )
    context = _passed_volume_context("dry_up_base", avg_return_pct=0.30)

    decision = discipline.decide_volume_probe(
        "000001",
        context,
        PaperBroker(100000),
        intent_profile=None,
    )

    assert decision.side is None
    assert "support_quality_dry_up_low_edge" in decision.reason


def test_volume_probe_dry_up_guard_blocks_markdown_stage() -> None:
    discipline = TradeDiscipline(
        DisciplineConfig(
            enable_volume_price_probe=True,
            enable_volume_price_dry_up_guard=True,
        )
    )
    context = _passed_volume_context("dry_up_base")
    profile = _profile(
        stage="markdown_risk",
        weekly_trend="base_down",
        close_vs_vwap60=-2.0,
        distribution_score=20.0,
    )

    decision = discipline.decide_volume_probe(
        "000001",
        context,
        PaperBroker(100000),
        intent_profile=profile,
    )

    assert decision.side is None
    assert "dry_up_guard_blocked_stage" in decision.reason


def test_volume_probe_dry_up_guard_blocks_weekly_down() -> None:
    discipline = TradeDiscipline(
        DisciplineConfig(
            enable_volume_price_probe=True,
            enable_volume_price_dry_up_guard=True,
        )
    )
    context = _passed_volume_context("dry_up_base")
    profile = _profile(
        stage="neutral",
        weekly_trend="down",
        close_vs_vwap60=-2.0,
        distribution_score=20.0,
    )

    decision = discipline.decide_volume_probe(
        "000001",
        context,
        PaperBroker(100000),
        intent_profile=profile,
    )

    assert decision.side is None
    assert "dry_up_guard_blocked_weekly_trend" in decision.reason


def test_volume_probe_dry_up_guard_blocks_negative_flow_10_when_available() -> None:
    discipline = TradeDiscipline(
        DisciplineConfig(
            enable_volume_price_probe=True,
            enable_volume_price_dry_up_guard=True,
            volume_price_dry_up_require_nonnegative_main_flow_10=True,
        )
    )
    context = _passed_volume_context("dry_up_base")
    profile = _profile(
        stage="neutral",
        weekly_trend="base_up",
        close_vs_vwap60=-2.0,
        main_flow_10=-1.0,
        distribution_score=20.0,
    )

    decision = discipline.decide_volume_probe(
        "000001",
        context,
        PaperBroker(100000),
        intent_profile=profile,
    )

    assert decision.side is None
    assert "dry_up_guard_negative_main_flow_10" in decision.reason


def test_volume_probe_dry_up_guard_allows_qualified_profile() -> None:
    discipline = TradeDiscipline(
        DisciplineConfig(
            enable_volume_price_probe=True,
            enable_volume_price_dry_up_guard=True,
            volume_price_dry_up_max_distribution_score=40.0,
            volume_price_dry_up_require_nonnegative_main_flow_10=True,
        )
    )
    context = _passed_volume_context("dry_up_base")
    profile = _profile(
        stage="neutral",
        weekly_trend="base_up",
        close_vs_vwap60=-2.0,
        main_flow_10=None,
        distribution_score=40.0,
    )

    decision = discipline.decide_volume_probe(
        "000001",
        context,
        PaperBroker(100000),
        intent_profile=profile,
    )

    assert decision.side == OrderSide.BUY
    assert "volume_price_trial_entry" in decision.reason


def test_volume_probe_dry_up_opening_guard_blocks_wide_support_distance() -> None:
    bars: list[Bar] = []
    start = date(2026, 1, 1)
    _append_base(bars, start)
    _append_positive_shrink_case(bars, start)
    _append_base(bars, start)
    _append_positive_shrink_case(bars, start)
    _append_base(bars, start)
    signal_index = len(bars)
    bars.append(
        Bar(
            symbol="000001",
            trade_date=start + timedelta(days=signal_index),
            open=10.21,
            high=10.24,
            low=9.80,
            close=10.16,
            volume=500,
            amount=10.16 * 500,
            change_pct=-0.5,
            turnover_rate=2.0,
        )
    )
    bars.append(_bar(start + timedelta(days=len(bars)), open_price=10.10, close=10.20))
    discipline = TradeDiscipline(
        DisciplineConfig(
            enable_volume_price_probe=True,
            enable_volume_price_dry_up_guard=True,
            volume_price_probe_min_cases=2,
            volume_price_dry_up_max_support_distance_pct=2.0,
        )
    )

    confirmed = discipline.confirm_volume_probe_opening(
        decision=TradeDecision(
            side=OrderSide.BUY,
            reason="volume_price_trial_entry: node=dry_up_base",
            target_weight=0.06,
        ),
        bars=bars,
        signal_index=signal_index,
        execution_index=signal_index + 1,
    )

    assert confirmed.side is None
    assert "dry_up_support_distance_too_wide" in confirmed.reason


def test_volume_probe_risk_sizing_keeps_base_weight_when_raw_stop_too_narrow() -> None:
    bars: list[Bar] = []
    start = date(2026, 1, 1)
    _append_base(bars, start)
    _append_positive_shrink_case(bars, start)
    _append_base(bars, start)
    _append_positive_shrink_case(bars, start)
    _append_base(bars, start)
    signal_index = len(bars)
    bars.append(_shrink_bar(start + timedelta(days=signal_index), 10.16))
    bars.append(_bar(start + timedelta(days=len(bars)), open_price=10.10, close=10.20))

    discipline = TradeDiscipline(
        DisciplineConfig(
            enable_volume_price_probe=True,
            enable_volume_price_risk_sizing=True,
            volume_price_probe_weight=0.06,
            volume_price_probe_window=3,
            volume_price_probe_min_cases=2,
            volume_price_probe_min_win_rate_pct=50.0,
            volume_price_probe_min_avg_return_pct=0.10,
            volume_price_account_risk_pct=0.003,
            volume_price_risk_sizing_max_weight=0.12,
            volume_price_min_stop_distance_pct=0.015,
            volume_price_min_raw_stop_upsize_pct=0.01,
        )
    )

    confirmed = discipline.confirm_volume_probe_opening(
        decision=TradeDecision(
            side=OrderSide.BUY,
            reason="volume_price_trial_entry: node=shrink_pullback",
            target_weight=0.06,
        ),
        bars=bars,
        signal_index=signal_index,
        execution_index=signal_index + 1,
    )

    assert confirmed.side == OrderSide.BUY
    assert confirmed.target_weight == 0.06
    assert "volume_price_support_base_weight" in confirmed.reason


def test_opening_expectation_uses_only_prior_opening_cases() -> None:
    bars: list[Bar] = []
    start = date(2026, 1, 1)
    _append_base(bars, start)
    _append_positive_shrink_case(bars, start, entry_gap_pct=-1.0)
    _append_base(bars, start)
    _append_positive_shrink_case(bars, start, entry_gap_pct=-1.2)
    _append_base(bars, start)
    signal_index = len(bars)
    bars.append(_shrink_bar(start + timedelta(days=signal_index), 10.00))
    bars.append(_bar(start + timedelta(days=len(bars)), open_price=9.90, close=10.00))
    _append_positive_shrink_case(bars, start, entry_gap_pct=8.0)

    expectation = build_volume_probe_opening_expectation(
        bars=bars,
        signal_index=signal_index,
        execution_index=signal_index + 1,
        config=OpeningExpectationConfig(window=3, min_cases=2, max_cases=12),
    )

    assert expectation.sample_cases == 2
    assert expectation.expected_gap_pct is not None
    assert expectation.expected_gap_pct < 0
    assert all(item.signal_date < bars[signal_index].trade_date for item in expectation.cases)


def test_volume_probe_strategy_mode_enables_volume_gate_only() -> None:
    config = discipline_config_for_mode("volume-probe")

    assert config.enable_volume_price_probe
    assert not config.enable_signal_entries
    assert not config.enable_pursuit_probe


def test_volume_probe_intent_filter_blocks_weak_dry_up_base() -> None:
    discipline = TradeDiscipline(
        DisciplineConfig(
            enable_volume_price_probe=True,
            enable_volume_price_intent_filter=True,
        )
    )
    context = _passed_volume_context("dry_up_base")
    profile = _profile(
        stage="neutral",
        weekly_trend="base_down",
        close_vs_vwap60=-6.8,
    )

    decision = discipline.decide_volume_probe(
        "000001",
        context,
        PaperBroker(100000),
        intent_profile=profile,
    )

    assert decision.side is None
    assert "intent_filter_dry_up_far_below_vwap60" in decision.reason


def test_volume_probe_intent_filter_blocks_quiet_weekly_down() -> None:
    discipline = TradeDiscipline(
        DisciplineConfig(
            enable_volume_price_probe=True,
            enable_volume_price_intent_filter=True,
        )
    )
    context = _passed_volume_context("quiet_consolidation")
    profile = _profile(
        stage="neutral",
        weekly_trend="down",
        close_vs_vwap60=-2.0,
    )

    decision = discipline.decide_volume_probe(
        "000001",
        context,
        PaperBroker(100000),
        intent_profile=profile,
    )

    assert decision.side is None
    assert "intent_filter_quiet_weekly_down" in decision.reason


def test_volume_probe_quiet_weekly_down_exception_blocks_weak_sample() -> None:
    discipline = TradeDiscipline(
        DisciplineConfig(
            enable_volume_price_probe=True,
            enable_volume_price_intent_filter=True,
            enable_volume_price_quiet_weekly_down_exception=True,
        )
    )
    context = _passed_volume_context(
        "quiet_consolidation",
        resolved_cases=4,
        win_rate_pct=70.0,
        avg_return_pct=0.70,
    )
    profile = _profile(
        stage="neutral",
        weekly_trend="down",
        close_vs_vwap60=-2.0,
        distribution_score=40.0,
    )

    decision = discipline.decide_volume_probe(
        "000001",
        context,
        PaperBroker(100000),
        intent_profile=profile,
    )

    assert decision.side is None
    assert "intent_filter_quiet_weekly_down" in decision.reason


def test_volume_probe_quiet_weekly_down_exception_allows_strong_sample() -> None:
    discipline = TradeDiscipline(
        DisciplineConfig(
            enable_volume_price_probe=True,
            enable_volume_price_intent_filter=True,
            enable_volume_price_quiet_weekly_down_exception=True,
        )
    )
    context = _passed_volume_context(
        "quiet_consolidation",
        resolved_cases=5,
        win_rate_pct=65.0,
        avg_return_pct=0.50,
    )
    profile = _profile(
        stage="neutral",
        weekly_trend="down",
        close_vs_vwap60=-2.0,
        distribution_score=65.0,
    )

    decision = discipline.decide_volume_probe(
        "000001",
        context,
        PaperBroker(100000),
        intent_profile=profile,
    )

    assert decision.side == OrderSide.BUY
    assert "volume_price_trial_entry" in decision.reason


def test_volume_probe_quiet_weekly_down_flow_guard_blocks_negative_flow_10() -> None:
    discipline = TradeDiscipline(
        DisciplineConfig(
            enable_volume_price_probe=True,
            enable_volume_price_intent_filter=True,
            enable_volume_price_quiet_weekly_down_exception=True,
            enable_volume_price_quiet_weekly_down_exception_flow_guard=True,
            volume_price_quiet_weekly_down_exception_min_cases=10,
            volume_price_quiet_weekly_down_exception_min_main_flow_10=0.0,
            volume_price_quiet_weekly_down_exception_max_distribution_score=40.0,
        )
    )
    context = _passed_volume_context(
        "quiet_consolidation",
        resolved_cases=10,
        win_rate_pct=65.0,
        avg_return_pct=0.50,
    )
    profile = _profile(
        stage="neutral",
        weekly_trend="down",
        close_vs_vwap60=-2.0,
        main_flow_10=-1.0,
        distribution_score=20.0,
    )

    decision = discipline.decide_volume_probe(
        "000001",
        context,
        PaperBroker(100000),
        intent_profile=profile,
    )

    assert decision.side is None
    assert "intent_filter_quiet_weekly_down" in decision.reason
    assert "main_flow_10=-1.00" in decision.reason


def test_volume_probe_quiet_weekly_down_flow_guard_allows_nonnegative_flow_10() -> None:
    discipline = TradeDiscipline(
        DisciplineConfig(
            enable_volume_price_probe=True,
            enable_volume_price_intent_filter=True,
            enable_volume_price_quiet_weekly_down_exception=True,
            enable_volume_price_quiet_weekly_down_exception_flow_guard=True,
            volume_price_quiet_weekly_down_exception_min_cases=10,
            volume_price_quiet_weekly_down_exception_min_main_flow_10=0.0,
            volume_price_quiet_weekly_down_exception_max_distribution_score=40.0,
        )
    )
    context = _passed_volume_context(
        "quiet_consolidation",
        resolved_cases=10,
        win_rate_pct=65.0,
        avg_return_pct=0.50,
    )
    profile = _profile(
        stage="neutral",
        weekly_trend="down",
        close_vs_vwap60=-2.0,
        main_flow_10=0.0,
        distribution_score=40.0,
    )

    decision = discipline.decide_volume_probe(
        "000001",
        context,
        PaperBroker(100000),
        intent_profile=profile,
    )

    assert decision.side == OrderSide.BUY
    assert "volume_price_trial_entry" in decision.reason


def test_volume_probe_node_quality_blocks_low_edge_quiet_node() -> None:
    discipline = TradeDiscipline(
        DisciplineConfig(
            enable_volume_price_probe=True,
            enable_volume_price_node_quality_filter=True,
            volume_price_node_quality_min_avg_return_pct=0.50,
            volume_price_node_quality_min_win_rate_pct=60.0,
        )
    )
    context = _passed_volume_context("quiet_consolidation", avg_return_pct=0.30)
    profile = _profile(
        stage="accumulation_watch",
        daily_trend="up",
        weekly_trend="up",
        close_vs_vwap60=2.0,
        main_flow_5=1_000_000.0,
        distribution_score=30.0,
    )

    decision = discipline.decide_volume_probe(
        "000001",
        context,
        PaperBroker(100000),
        intent_profile=profile,
    )

    assert decision.side is None
    assert "node_quality_low_edge" in decision.reason


def test_volume_probe_node_quality_blocks_weak_shrink_flow() -> None:
    discipline = TradeDiscipline(
        DisciplineConfig(
            enable_volume_price_probe=True,
            enable_volume_price_node_quality_filter=True,
            volume_price_node_quality_min_avg_return_pct=0.35,
            volume_price_node_quality_min_win_rate_pct=60.0,
        )
    )
    context = _passed_volume_context("shrink_pullback", avg_return_pct=0.55)
    profile = _profile(
        stage="neutral",
        daily_trend="base_down",
        weekly_trend="base_down",
        close_vs_vwap60=-2.0,
        main_flow_5=-10_000.0,
        distribution_score=40.0,
    )

    decision = discipline.decide_volume_probe(
        "000001",
        context,
        PaperBroker(100000),
        intent_profile=profile,
    )

    assert decision.side is None
    assert "node_quality_weak_main_flow" in decision.reason


def test_volume_probe_node_quality_allows_valid_shrink_node() -> None:
    discipline = TradeDiscipline(
        DisciplineConfig(
            enable_volume_price_probe=True,
            enable_volume_price_node_quality_filter=True,
            volume_price_node_quality_min_avg_return_pct=0.35,
            volume_price_node_quality_min_win_rate_pct=60.0,
        )
    )
    context = _passed_volume_context("shrink_pullback", avg_return_pct=0.55)
    profile = _profile(
        stage="accumulation_watch",
        daily_trend="base_up",
        weekly_trend="up",
        close_vs_vwap60=1.5,
        main_flow_5=1_000_000.0,
        distribution_score=30.0,
    )

    decision = discipline.decide_volume_probe(
        "000001",
        context,
        PaperBroker(100000),
        intent_profile=profile,
    )

    assert decision.side == OrderSide.BUY
    assert "volume_price_trial_entry" in decision.reason


def _volume_probe_discipline() -> TradeDiscipline:
    return TradeDiscipline(
        DisciplineConfig(
            enable_signal_entries=False,
            enable_pursuit_probe=False,
            enable_confirmation_add=False,
            enable_volume_price_probe=True,
            volume_price_probe_weight=0.10,
            volume_price_probe_window=3,
            volume_price_probe_min_cases=2,
            volume_price_probe_min_win_rate_pct=50.0,
            volume_price_probe_min_avg_return_pct=0.10,
        )
    )


def _risk_sizing_discipline() -> TradeDiscipline:
    return TradeDiscipline(
        DisciplineConfig(
            enable_signal_entries=False,
            enable_pursuit_probe=False,
            enable_confirmation_add=False,
            enable_volume_price_probe=True,
            enable_volume_price_risk_sizing=True,
            volume_price_probe_weight=0.06,
            volume_price_probe_window=3,
            volume_price_probe_min_cases=2,
            volume_price_probe_min_win_rate_pct=50.0,
            volume_price_probe_min_avg_return_pct=0.10,
            volume_price_account_risk_pct=0.003,
            volume_price_risk_sizing_max_weight=0.12,
            volume_price_min_stop_distance_pct=0.015,
        )
    )


def _follow_through_discipline() -> TradeDiscipline:
    return TradeDiscipline(
        DisciplineConfig(
            enable_signal_entries=False,
            enable_pursuit_probe=False,
            enable_confirmation_add=False,
            enable_volume_price_probe=True,
            enable_volume_price_follow_through_exit=True,
            volume_price_follow_through_no_confirm_bars=3,
            volume_price_follow_through_max_hold_bars=5,
        )
    )


def _breakout_confirmation_discipline() -> TradeDiscipline:
    return TradeDiscipline(
        DisciplineConfig(
            enable_signal_entries=False,
            enable_pursuit_probe=False,
            enable_confirmation_add=False,
            enable_volume_price_probe=True,
            enable_volume_price_timed_exit=False,
            enable_volume_price_opening_gate=False,
            volume_price_probe_allowed_node_types=("volume_breakout",),
            volume_price_probe_window=3,
            volume_price_probe_min_cases=2,
            volume_price_probe_min_win_rate_pct=50.0,
            volume_price_probe_min_avg_return_pct=0.10,
            enable_volume_price_breakout_confirmation_entry=True,
            volume_price_breakout_confirmation_bars=1,
        )
    )


def _pre_breakout_watchlist_discipline() -> TradeDiscipline:
    return TradeDiscipline(
        DisciplineConfig(
            enable_signal_entries=False,
            enable_pursuit_probe=False,
            enable_confirmation_add=False,
            enable_volume_price_probe=True,
            enable_volume_price_timed_exit=False,
            enable_volume_price_opening_gate=False,
            volume_price_probe_allowed_node_types=("volume_breakout",),
            volume_price_probe_window=5,
            volume_price_probe_min_cases=99,
            volume_price_probe_min_win_rate_pct=99.0,
            volume_price_probe_min_avg_return_pct=99.0,
            enable_volume_price_pre_breakout_watchlist_entry=True,
            volume_price_pre_breakout_watch_node_types=(
                "normal",
                "dry_up_base",
                "quiet_consolidation",
                "shrink_pullback",
            ),
            volume_price_pre_breakout_max_age_bars=5,
            volume_price_pre_breakout_observation_weight=0.05,
            volume_price_pre_breakout_strong_weight=0.10,
            volume_price_pre_breakout_continuous_weight=0.15,
        )
    )


def _broker_with_volume_buy(
    bar: Bar,
    *,
    reason_support: float,
    execute_price: float | None = None,
) -> PaperBroker:
    broker = PaperBroker(100000)
    broker.execute_market_order(
        Order(
            symbol="000001",
            side=OrderSide.BUY,
            quantity=1000,
            reason=(
                "volume_price_trial_entry: node=volume_breakout; "
                f"volume_price_risk_sized: support={reason_support:.2f}"
            ),
        ),
        execute_price if execute_price is not None else bar.open,
        bar.trade_date,
    )
    return broker


def _follow_through_bars(
    *,
    closes: tuple[float, ...],
    changes: tuple[float, ...],
) -> list[Bar]:
    start = date(2026, 1, 1)
    return [
        Bar(
            symbol="000001",
            trade_date=start + timedelta(days=index),
            open=close,
            high=close + 0.10,
            low=close - 0.10,
            close=close,
            volume=1_000,
            amount=close * 1_000,
            change_pct=changes[index],
            turnover_rate=3.0,
        )
        for index, close in enumerate(closes)
    ]


def _passed_volume_context(
    node_type: str,
    *,
    resolved_cases: int = 8,
    avg_return_pct: float = 0.45,
    win_rate_pct: float = 62.0,
) -> VolumeProbeContext:
    return VolumeProbeContext(
        as_of_date=date(2026, 1, 1),
        node=VolumePriceNode(
            trade_date=date(2026, 1, 1),
            close=10.0,
            change_pct=0.2,
            volume_ratio=0.6,
            node_type=node_type,
            volume_state="shrink",
            price_position="near_low",
            range_position_pct=20.0,
            main_flow=None,
            main_pct=None,
            interpretation="test",
        ),
        resolved_cases=resolved_cases,
        win_rate_pct=win_rate_pct,
        avg_return_pct=avg_return_pct,
        avg_win_pct=0.7,
        avg_loss_pct=-0.2,
        passed=True,
        reason="passed_same_node_history_gate",
    )


def _profile(
    *,
    stage: str,
    weekly_trend: str,
    close_vs_vwap60: float | None,
    daily_trend: str = "base_down",
    main_flow_3: float | None = None,
    main_flow_5: float | None = None,
    main_flow_10: float | None = None,
    distribution_score: float = 40.0,
) -> MainForceProfile:
    return MainForceProfile(
        trade_date=date(2026, 1, 1),
        close=10.0,
        daily_trend=daily_trend,
        weekly_trend=weekly_trend,
        monthly_trend="base_down",
        stage=stage,
        vwap_60=10.0,
        vwap_120=None,
        close_vs_vwap_60_pct=close_vs_vwap60,
        close_vs_vwap_120_pct=None,
        turnover_20=None,
        turnover_60=None,
        main_flow_3=main_flow_3,
        main_flow_5=main_flow_5,
        main_flow_10=main_flow_10,
        obv_slope_20=None,
        adl_slope_20=None,
        accumulation_score=35.0,
        markup_score=0.0,
        distribution_score=distribution_score,
    )


def _append_base(bars: list[Bar], start: date) -> None:
    for _ in range(3):
        trade_date = start + timedelta(days=len(bars))
        bars.append(
            Bar(
                symbol="000001",
                trade_date=trade_date,
                open=10.0,
                high=10.8,
                low=9.2,
                close=10.0,
                volume=1_000,
                amount=10_000,
                change_pct=0.1,
                turnover_rate=3.0,
            )
        )


def _append_positive_shrink_case(
    bars: list[Bar],
    start: date,
    *,
    entry_gap_pct: float = -1.96,
) -> None:
    signal_date = start + timedelta(days=len(bars))
    signal_close = 10.20
    entry_open = signal_close * (1 + entry_gap_pct / 100)
    bars.append(_shrink_bar(signal_date, signal_close))
    bars.append(_bar(start + timedelta(days=len(bars)), open_price=entry_open, close=entry_open + 0.10))
    bars.append(_bar(start + timedelta(days=len(bars)), open_price=entry_open + 0.40, close=entry_open + 0.45))


def _append_breakout_base(bars: list[Bar], start: date) -> None:
    for index in range(3):
        trade_date = start + timedelta(days=len(bars))
        close = 10.0 + index * 0.05
        bars.append(
            Bar(
                symbol="000001",
                trade_date=trade_date,
                open=close,
                high=10.50,
                low=9.80,
                close=close,
                volume=1_000,
                amount=close * 1_000,
                change_pct=0.5,
                turnover_rate=3.0,
            )
        )


def _append_positive_breakout_case(
    bars: list[Bar],
    start: date,
    *,
    change_pct: float,
    entry_gap_pct: float = -0.91,
) -> None:
    signal_date = start + timedelta(days=len(bars))
    signal_close = 11.00
    entry_open = signal_close * (1 + entry_gap_pct / 100)
    bars.append(_breakout_bar(signal_date, signal_close, change_pct=change_pct))
    bars.append(_bar(start + timedelta(days=len(bars)), open_price=entry_open, close=entry_open + 0.20))
    bars.append(_bar(start + timedelta(days=len(bars)), open_price=entry_open + 0.40, close=entry_open + 0.45))


def _breakout_confirmation_dataset(
    *,
    confirm_close: float,
    confirm_main_flow: float,
    confirm_low: float | None = None,
) -> tuple[list[Bar], list[FundFlowSnapshot], int]:
    bars: list[Bar] = []
    start = date(2026, 1, 1)
    _append_breakout_base(bars, start)
    _append_positive_breakout_case(bars, start, change_pct=3.0, entry_gap_pct=0.5)
    _append_breakout_base(bars, start)
    _append_positive_breakout_case(bars, start, change_pct=3.2, entry_gap_pct=0.6)
    _append_breakout_base(bars, start)
    signal_index = len(bars)
    bars.append(
        Bar(
            symbol="000001",
            trade_date=start + timedelta(days=signal_index),
            open=10.42,
            high=10.68,
            low=10.30,
            close=10.60,
            volume=2_000,
            amount=10.60 * 2_000,
            change_pct=3.0,
            turnover_rate=5.0,
        )
    )
    bars.append(
        Bar(
            symbol="000001",
            trade_date=start + timedelta(days=len(bars)),
            open=10.58,
            high=max(10.75, confirm_close + 0.04),
            low=confirm_low if confirm_low is not None else 10.52,
            close=confirm_close,
            volume=1_500,
            amount=confirm_close * 1_500,
            change_pct=(confirm_close / 10.60 - 1) * 100,
            turnover_rate=4.8,
        )
    )
    bars.append(
        Bar(
            symbol="000001",
            trade_date=start + timedelta(days=len(bars)),
            open=10.76,
            high=10.86,
            low=10.66,
            close=10.82,
            volume=1_300,
            amount=10.82 * 1_300,
            change_pct=0.9,
            turnover_rate=4.0,
        )
    )
    flows = [_flow_for_bar(item, main_flow=300_000.0) for item in bars]
    flows[signal_index] = _flow_for_bar(bars[signal_index], main_flow=800_000.0)
    flows[signal_index + 1] = _flow_for_bar(
        bars[signal_index + 1],
        main_flow=confirm_main_flow,
    )
    return bars, flows, signal_index


def _pre_breakout_watch_dataset(
    *,
    confirmation_main_flow: float,
) -> tuple[list[Bar], list[FundFlowSnapshot], int, int]:
    bars: list[Bar] = []
    start = date(2026, 1, 1)
    _append_breakout_base(bars, start)
    watch_index = len(bars)
    bars.append(_quiet_bar(start + timedelta(days=watch_index), 10.10))
    confirmation_index = len(bars)
    bars.append(
        Bar(
            symbol="000001",
            trade_date=start + timedelta(days=confirmation_index),
            open=10.35,
            high=10.86,
            low=10.28,
            close=10.70,
            volume=2_500,
            amount=10.70 * 2_500,
            change_pct=4.0,
            turnover_rate=5.0,
        )
    )
    bars.append(
        Bar(
            symbol="000001",
            trade_date=start + timedelta(days=len(bars)),
            open=10.72,
            high=10.92,
            low=10.60,
            close=10.85,
            volume=1_500,
            amount=10.85 * 1_500,
            change_pct=1.4,
            turnover_rate=4.0,
        )
    )
    flows = [_flow_for_bar(item, main_flow=200_000.0) for item in bars]
    flows[confirmation_index] = _flow_for_bar(
        bars[confirmation_index],
        main_flow=confirmation_main_flow,
    )
    return bars, flows, watch_index, confirmation_index


def _breakout_bar(trade_date: date, close: float, *, change_pct: float) -> Bar:
    return Bar(
        symbol="000001",
        trade_date=trade_date,
        open=close - 0.15,
        high=close + 0.10,
        low=close - 0.25,
        close=close,
        volume=2_500,
        amount=close * 2_500,
        change_pct=change_pct,
        turnover_rate=5.0,
    )


def _breakout_bar_with_low(
    trade_date: date,
    close: float,
    *,
    change_pct: float,
    low: float,
) -> Bar:
    return Bar(
        symbol="000001",
        trade_date=trade_date,
        open=close - 0.15,
        high=close + 0.10,
        low=low,
        close=close,
        volume=2_500,
        amount=close * 2_500,
        change_pct=change_pct,
        turnover_rate=5.0,
    )


def _shrink_bar(trade_date: date, close: float) -> Bar:
    return Bar(
        symbol="000001",
        trade_date=trade_date,
        open=close + 0.05,
        high=close + 0.08,
        low=close - 0.12,
        close=close,
        volume=500,
        amount=close * 500,
        change_pct=-0.5,
        turnover_rate=2.0,
    )


def _quiet_bar(trade_date: date, close: float) -> Bar:
    return Bar(
        symbol="000001",
        trade_date=trade_date,
        open=close - 0.02,
        high=close + 0.03,
        low=close - 0.03,
        close=close,
        volume=500,
        amount=close * 500,
        change_pct=0.2,
        turnover_rate=2.0,
    )


def _bar(trade_date: date, *, open_price: float, close: float) -> Bar:
    return Bar(
        symbol="000001",
        trade_date=trade_date,
        open=open_price,
        high=max(open_price, close) + 0.05,
        low=min(open_price, close) - 0.05,
        close=close,
        volume=1_000,
        amount=close * 1_000,
        change_pct=0.5,
        turnover_rate=3.0,
    )


def _flow_for_bar(bar: Bar, *, main_flow: float) -> FundFlowSnapshot:
    return FundFlowSnapshot(
        symbol=bar.symbol,
        name="test",
        timestamp=datetime.combine(bar.trade_date, datetime.min.time()),
        super_large_net_inflow=main_flow / 2,
        large_net_inflow=main_flow / 2,
        medium_net_inflow=0.0,
        small_net_inflow=0.0,
        main_net_inflow_pct=6.0 if main_flow >= 0 else -6.0,
        change_pct=bar.change_pct,
        amount=bar.amount,
        turnover_rate=bar.turnover_rate,
        provider="test",
        period="daily",
    )
