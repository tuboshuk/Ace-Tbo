"""Convert monitor signals into paper-trading discipline decisions."""

from __future__ import annotations

from dataclasses import dataclass
import re

from wealth_lab.accumulation_proof import (
    AccumulationProofContext,
    is_disguised_accumulation_candidate,
)
from wealth_lab.models import (
    Bar,
    Fill,
    FundSignal,
    MainForceProfile,
    Order,
    OrderSide,
    PatternTag,
    Quote,
    StockSignal,
)
from wealth_lab.paper import PaperBroker
from wealth_lab.rules import round_down_to_lot
from wealth_lab.trade_quality import (
    estimate_entry_quality,
    estimate_inferred_exit_pressure,
)
from wealth_lab.volume_probe import (
    DEFAULT_ALLOWED_VOLUME_PROBE_NODES,
    OpeningExpectation,
    OpeningExpectationConfig,
    VolumeProbeConfig,
    VolumeProbeContext,
    build_point_in_time_volume_probe_context,
    build_volume_probe_opening_expectation,
)


@dataclass(frozen=True)
class TradeDecision:
    """A paper-trading decision generated from a stock signal."""

    side: OrderSide | None
    reason: str
    target_weight: float = 0.0

    @property
    def is_trade(self) -> bool:
        """Return whether the decision should attempt a paper order."""

        return self.side is not None


@dataclass(frozen=True)
class DisciplineConfig:
    """Risk and sizing settings for signal-based paper trading."""

    breakout_weight: float = 0.35
    accumulation_weight: float = 0.25
    stop_loss_pct: float = 0.08
    max_single_position_weight: float = 0.45
    min_accumulation_score: float = 65.0
    min_markup_score: float = 55.0
    max_distribution_entry_score: float = 65.0
    exit_distribution_score: float = 75.0
    max_breakout_close_vs_vwap60_pct: float = 12.0
    max_breakout_turnover_rate: float = 15.0
    pursuit_probe_weight: float = 0.10
    enable_pursuit_probe: bool = True
    min_pursuit_main_pct: float = 8.0
    max_pursuit_distribution_score: float = 65.0
    min_pursuit_volume_ratio: float = 1.5
    enable_accumulation_proof_probe: bool = False
    accumulation_proof_probe_weight: float = 0.08
    accumulation_proof_horizon: int = 5
    min_accumulation_proof_cases: int = 5
    min_accumulation_proof_rate_pct: float = 60.0
    enable_confirmation_add: bool = True
    min_entry_reward_risk: float = 1.2
    enable_active_probe: bool = False
    enable_inferred_exit: bool = False
    enable_signal_entries: bool = True
    enable_volume_price_probe: bool = False
    volume_price_probe_weight: float = 0.06
    volume_price_probe_window: int = 20
    volume_price_probe_exit_offset_bars: int = 2
    volume_price_probe_min_cases: int = 5
    volume_price_probe_min_win_rate_pct: float = 55.0
    volume_price_probe_min_avg_return_pct: float = 0.20
    volume_price_probe_allowed_node_types: tuple[str, ...] = DEFAULT_ALLOWED_VOLUME_PROBE_NODES
    enable_volume_price_timed_exit: bool = True
    enable_volume_price_opening_gate: bool = True
    enable_volume_price_intent_filter: bool = False
    volume_price_dry_up_min_close_vs_vwap60_pct: float = -6.0
    volume_price_block_quiet_weekly_down: bool = True
    enable_volume_price_quiet_weekly_down_exception: bool = False
    volume_price_quiet_weekly_down_exception_min_cases: int = 5
    volume_price_quiet_weekly_down_exception_min_win_rate_pct: float = 65.0
    volume_price_quiet_weekly_down_exception_min_avg_return_pct: float = 0.50
    volume_price_quiet_weekly_down_exception_max_distribution_score: float = 65.0
    enable_volume_price_quiet_weekly_down_exception_flow_guard: bool = False
    volume_price_quiet_weekly_down_exception_min_main_flow_10: float | None = None
    volume_price_block_non_breakout_markdown: bool = True
    enable_volume_price_main_force_profile_filter: bool = False
    volume_price_main_force_allowed_stages: tuple[str, ...] = (
        "accumulation_watch",
        "markup_confirmed",
    )
    volume_price_main_force_max_distribution_score: float | None = 55.0
    volume_price_main_force_require_positive_flow_majority: bool = True
    enable_volume_price_weak_main_force_block: bool = False
    volume_price_weak_main_force_block_stages: tuple[str, ...] = (
        "distribution_risk",
        "failed_breakout",
    )
    volume_price_weak_main_force_min_negative_flow_windows: int = 2
    volume_price_weak_main_force_distribution_score: float | None = 65.0
    enable_volume_price_support_quality_filter: bool = False
    volume_price_block_dry_up_without_main_flow: bool = False
    volume_price_support_quality_min_dry_up_avg_return_pct: float = 0.35
    enable_volume_price_dry_up_guard: bool = False
    volume_price_dry_up_block_stages: tuple[str, ...] = ("markdown_risk",)
    volume_price_dry_up_block_weekly_trends: tuple[str, ...] = ("down",)
    volume_price_dry_up_max_distribution_score: float | None = None
    volume_price_dry_up_require_nonnegative_main_flow_10: bool = False
    volume_price_dry_up_min_support_distance_pct: float | None = None
    volume_price_dry_up_max_support_distance_pct: float | None = None
    volume_price_dry_up_max_opening_gap_pct: float | None = None
    enable_volume_price_node_quality_filter: bool = False
    volume_price_node_quality_node_types: tuple[str, ...] = (
        "volume_breakout",
        "shrink_pullback",
        "quiet_consolidation",
    )
    volume_price_node_quality_min_avg_return_pct: float = 0.35
    volume_price_node_quality_min_win_rate_pct: float = 60.0
    volume_price_node_quality_min_main_flow_5: float | None = 0.0
    volume_price_node_quality_allowed_daily_trends: tuple[str, ...] = (
        "up",
        "base_up",
    )
    volume_price_node_quality_allowed_weekly_trends: tuple[str, ...] = (
        "up",
        "base_up",
    )
    volume_price_node_quality_block_stages: tuple[str, ...] = (
        "markdown_risk",
        "distribution_risk",
    )
    volume_price_node_quality_max_distribution_score: float | None = 55.0
    enable_volume_price_risk_sizing: bool = False
    volume_price_account_risk_pct: float = 0.003
    volume_price_risk_sizing_max_weight: float = 0.12
    volume_price_risk_sizing_respects_decision_cap: bool = False
    volume_price_min_stop_distance_pct: float = 0.015
    volume_price_min_raw_stop_upsize_pct: float = 0.0
    volume_price_uncertain_open_weight_factor: float = 0.50
    enable_volume_price_follow_through_exit: bool = False
    volume_price_follow_through_no_confirm_bars: int = 3
    volume_price_follow_through_max_hold_bars: int = 5
    volume_price_follow_through_first_bar_exit_requires_loss: bool = False
    volume_price_follow_through_exit_on_negative_main_flow: bool = False
    volume_price_follow_through_exit_on_profitable_stall: bool = False
    enable_volume_price_breakout_confirmation_entry: bool = False
    volume_price_breakout_confirmation_bars: int = 1
    enable_volume_price_pre_breakout_watchlist_entry: bool = False
    volume_price_pre_breakout_watch_node_types: tuple[str, ...] = (
        "normal",
        "dry_up_base",
        "quiet_consolidation",
        "shrink_pullback",
    )
    volume_price_pre_breakout_max_age_bars: int = 5
    volume_price_pre_breakout_observation_weight: float = 0.05
    volume_price_pre_breakout_strong_weight: float = 0.10
    volume_price_pre_breakout_continuous_weight: float = 0.15
    volume_price_pre_breakout_allow_unknown_flow: bool = True
    volume_price_breakout_max_opening_gap_pct: float | None = None
    volume_price_breakout_wide_support_distance_pct: float | None = None
    volume_price_breakout_min_gap_for_wide_support_pct: float | None = None
    hot_breakout_change_pct: float = 7.0
    require_nonnegative_open_after_hot_breakout: bool = True
    require_open_above_signal_low: bool = True


def discipline_config_for_mode(mode: str) -> DisciplineConfig:
    """Return a compact strategy mode config for CLI use."""

    if mode == "baseline":
        return DisciplineConfig()
    if mode == "confirmed":
        return DisciplineConfig(enable_pursuit_probe=False)
    if mode == "proof-probe":
        return DisciplineConfig(
            enable_pursuit_probe=False,
            enable_accumulation_proof_probe=True,
            accumulation_proof_probe_weight=0.08,
        )
    if mode == "active-probe":
        return DisciplineConfig(
            breakout_weight=0.12,
            accumulation_weight=0.10,
            pursuit_probe_weight=0.08,
            enable_pursuit_probe=True,
            min_pursuit_main_pct=8.0,
            max_pursuit_distribution_score=60.0,
            max_breakout_turnover_rate=12.0,
            enable_active_probe=True,
            enable_inferred_exit=True,
            min_entry_reward_risk=1.2,
            exit_distribution_score=70.0,
        )
    if mode == "volume-probe":
        return DisciplineConfig(
            enable_signal_entries=False,
            enable_pursuit_probe=False,
            enable_confirmation_add=False,
            enable_volume_price_probe=True,
            volume_price_probe_weight=0.06,
            volume_price_probe_min_cases=5,
            volume_price_probe_min_win_rate_pct=55.0,
            volume_price_probe_min_avg_return_pct=0.20,
            stop_loss_pct=0.06,
        )
    raise ValueError(f"unknown strategy mode: {mode}")


class TradeDiscipline:
    """Map observation signals to conservative paper-trading actions."""

    def __init__(self, config: DisciplineConfig | None = None) -> None:
        self.config = config or DisciplineConfig()

    def decide(
        self,
        signal: StockSignal,
        broker: PaperBroker,
        proof_context: AccumulationProofContext | None = None,
    ) -> TradeDecision:
        """Return a paper-trading decision for the signal."""

        position = broker.positions.get(signal.symbol)
        has_position = bool(position and position.quantity > 0)
        if has_position and signal.quote is not None:
            stop_price = position.avg_cost * (1 - self.config.stop_loss_pct)
            if signal.quote.price <= stop_price:
                return TradeDecision(
                    side=OrderSide.SELL,
                    reason=f"stop_loss close={signal.quote.price:.2f} stop={stop_price:.2f}",
                )
        if has_position and signal.intent_profile is not None:
            profile = signal.intent_profile
            if profile.distribution_score >= self.config.exit_distribution_score:
                return TradeDecision(
                    side=OrderSide.SELL,
                    reason=(
                        "exit: distribution_score "
                        f"{profile.distribution_score:.1f}; {_tags(signal)}"
                    ),
                )

        if has_position and _is_exit_signal(signal):
            return TradeDecision(
                side=OrderSide.SELL,
                reason=f"exit: {signal.fund_signal.value}; {_tags(signal)}",
            )
        if (
            has_position
            and position is not None
            and self.config.enable_inferred_exit
        ):
            pressure = estimate_inferred_exit_pressure(signal, position.avg_cost)
            if pressure.triggered:
                return TradeDecision(
                    side=OrderSide.SELL,
                    reason=(
                        f"inferred_exit: score={pressure.score:.1f}; "
                        f"{','.join(pressure.reasons)}"
                    ),
                )

        if (
            has_position
            and self.config.enable_confirmation_add
            and _is_breakout_entry(signal, self.config)
        ):
            return TradeDecision(
                side=OrderSide.BUY,
                reason=f"confirmation_add: {signal.fund_signal.value}; {_tags(signal)}",
                target_weight=min(
                    self.config.breakout_weight,
                    self.config.max_single_position_weight,
                ),
            )

        if not self.config.enable_signal_entries:
            return TradeDecision(
                side=None,
                reason="hold/signal entries disabled by strategy mode",
            )

        if not has_position and is_disguised_accumulation_candidate(signal):
            if _is_accumulation_proof_probe_entry(proof_context, self.config):
                return TradeDecision(
                    side=OrderSide.BUY,
                    reason=(
                        "proof_probe_entry: "
                        f"rate={proof_context.confirmation_rate_pct:.2f}% "
                        f"resolved={proof_context.resolved}; {_tags(signal)}"
                    ),
                    target_weight=min(
                        self.config.accumulation_proof_probe_weight,
                        self.config.max_single_position_weight,
                    ),
                )
            return TradeDecision(
                side=None,
                reason=(
                    "wait_accumulation_proof: apparent selling plus small-order "
                    "absorption requires future support/recovery/flow confirmation"
                ),
            )

        if not has_position and _is_breakout_entry(signal, self.config):
            return TradeDecision(
                side=OrderSide.BUY,
                reason=f"breakout_entry: {signal.fund_signal.value}; {_tags(signal)}",
                target_weight=min(
                    self.config.breakout_weight,
                    self.config.max_single_position_weight,
                ),
            )

        if not has_position and _is_accumulation_entry(signal, self.config):
            return TradeDecision(
                side=OrderSide.BUY,
                reason=f"accumulation_entry: {signal.fund_signal.value}; {_tags(signal)}",
                target_weight=min(
                    self.config.accumulation_weight,
                    self.config.max_single_position_weight,
                ),
            )

        if not has_position and _is_active_probe_entry(signal, self.config):
            quality = estimate_entry_quality(signal, self.config.min_entry_reward_risk)
            return TradeDecision(
                side=OrderSide.BUY,
                reason=(
                    "active_probe_entry: "
                    f"rr={_fmt_optional(quality.reward_risk)} "
                    f"risk={_fmt_optional(quality.risk_pct)}%; "
                    f"{signal.fund_signal.value}; {_tags(signal)}"
                ),
                target_weight=min(
                    self.config.pursuit_probe_weight,
                    self.config.max_single_position_weight,
                ),
            )

        if not has_position and _is_pursuit_probe_entry(signal, self.config):
            return TradeDecision(
                side=OrderSide.BUY,
                reason=f"pursuit_probe_entry: {signal.fund_signal.value}; {_tags(signal)}",
                target_weight=min(
                    self.config.pursuit_probe_weight,
                    self.config.max_single_position_weight,
                ),
            )

        return TradeDecision(side=None, reason="hold/no paper-trade action")

    def volume_probe_config(self) -> VolumeProbeConfig:
        """Return the volume-price probe validation config."""

        return VolumeProbeConfig(
            window=self.config.volume_price_probe_window,
            exit_offset_bars=self.config.volume_price_probe_exit_offset_bars,
            min_cases=self.config.volume_price_probe_min_cases,
            min_win_rate_pct=self.config.volume_price_probe_min_win_rate_pct,
            min_avg_return_pct=self.config.volume_price_probe_min_avg_return_pct,
            allowed_node_types=self.config.volume_price_probe_allowed_node_types,
        )

    def build_volume_probe_context(
        self,
        bars: list[Bar],
        index: int,
    ) -> VolumeProbeContext:
        """Build point-in-time volume-price evidence for one replay day."""

        return build_point_in_time_volume_probe_context(
            bars=bars,
            index=index,
            config=self.volume_probe_config(),
        )

    def decide_volume_probe(
        self,
        symbol: str,
        context: VolumeProbeContext,
        broker: PaperBroker,
        intent_profile: MainForceProfile | None = None,
    ) -> TradeDecision:
        """Return a daily volume-price trial decision."""

        if not self.config.enable_volume_price_probe:
            return TradeDecision(side=None, reason="volume_price_trial_disabled")
        position = broker.positions.get(symbol)
        if position is not None and position.quantity > 0:
            return TradeDecision(side=None, reason="volume_price_trial_blocked: has_position")
        if not context.passed:
            return TradeDecision(
                side=None,
                reason=(
                    "volume_price_trial_blocked: "
                    f"node={context.node.node_type} "
                    f"cases={context.resolved_cases} "
                    f"win={_fmt_optional(context.win_rate_pct)}% "
                    f"avg={_fmt_optional(context.avg_return_pct)}%; "
                    f"{context.reason}"
                ),
            )
        intent_block = _volume_price_intent_block_reason(
            context=context,
            config=self.config,
            intent_profile=intent_profile,
        )
        if intent_block is not None:
            return TradeDecision(
                side=None,
                reason=(
                    "volume_price_trial_blocked: "
                    f"node={context.node.node_type} "
                    f"cases={context.resolved_cases} "
                    f"win={_fmt_optional(context.win_rate_pct)}% "
                    f"avg={_fmt_optional(context.avg_return_pct)}%; "
                    f"{intent_block}"
                ),
            )
        main_force_block = _volume_price_main_force_profile_block_reason(
            config=self.config,
            intent_profile=intent_profile,
        )
        if main_force_block is not None:
            return TradeDecision(
                side=None,
                reason=(
                    "volume_price_trial_blocked: "
                    f"node={context.node.node_type} "
                    f"cases={context.resolved_cases} "
                    f"win={_fmt_optional(context.win_rate_pct)}% "
                    f"avg={_fmt_optional(context.avg_return_pct)}%; "
                    f"{main_force_block}"
                ),
            )
        weak_main_force_block = _volume_price_weak_main_force_block_reason(
            config=self.config,
            intent_profile=intent_profile,
        )
        if weak_main_force_block is not None:
            return TradeDecision(
                side=None,
                reason=(
                    "volume_price_trial_blocked: "
                    f"node={context.node.node_type} "
                    f"cases={context.resolved_cases} "
                    f"win={_fmt_optional(context.win_rate_pct)}% "
                    f"avg={_fmt_optional(context.avg_return_pct)}%; "
                    f"{weak_main_force_block}"
                ),
            )
        support_quality_block = _volume_price_support_quality_block_reason(
            context=context,
            config=self.config,
            intent_profile=intent_profile,
        )
        if support_quality_block is not None:
            return TradeDecision(
                side=None,
                reason=(
                    "volume_price_trial_blocked: "
                    f"node={context.node.node_type} "
                    f"cases={context.resolved_cases} "
                    f"win={_fmt_optional(context.win_rate_pct)}% "
                    f"avg={_fmt_optional(context.avg_return_pct)}%; "
                    f"{support_quality_block}"
                ),
            )
        dry_up_block = _volume_price_dry_up_block_reason(
            context=context,
            config=self.config,
            intent_profile=intent_profile,
        )
        if dry_up_block is not None:
            return TradeDecision(
                side=None,
                reason=(
                    "volume_price_trial_blocked: "
                    f"node={context.node.node_type} "
                    f"cases={context.resolved_cases} "
                    f"win={_fmt_optional(context.win_rate_pct)}% "
                    f"avg={_fmt_optional(context.avg_return_pct)}%; "
                    f"{dry_up_block}"
                ),
            )
        node_quality_block = _volume_price_node_quality_block_reason(
            context=context,
            config=self.config,
            intent_profile=intent_profile,
        )
        if node_quality_block is not None:
            return TradeDecision(
                side=None,
                reason=(
                    "volume_price_trial_blocked: "
                    f"node={context.node.node_type} "
                    f"cases={context.resolved_cases} "
                    f"win={_fmt_optional(context.win_rate_pct)}% "
                    f"avg={_fmt_optional(context.avg_return_pct)}%; "
                    f"{node_quality_block}"
                ),
            )
        return TradeDecision(
            side=OrderSide.BUY,
            reason=(
                "volume_price_trial_entry: "
                f"node={context.node.node_type} "
                f"cases={context.resolved_cases} "
                f"win={_fmt_optional(context.win_rate_pct)}% "
                f"avg={_fmt_optional(context.avg_return_pct)}%; "
                f"{context.reason}"
            ),
            target_weight=min(
                self.config.volume_price_probe_weight,
                self.config.max_single_position_weight,
            ),
        )

    def should_observe_volume_breakout_confirmation_entry(
        self,
        decision: TradeDecision,
        intent_profile: MainForceProfile | None = None,
    ) -> bool:
        """Return whether a breakout trial should wait for one-bar confirmation."""

        if not self.config.enable_volume_price_breakout_confirmation_entry:
            return False
        return decision.is_trade and "node=volume_breakout" in decision.reason

    def confirm_volume_breakout_confirmation_entry(
        self,
        decision: TradeDecision,
        bars: list[Bar],
        signal_index: int,
        confirmation_index: int,
        *,
        main_flow: float | None = None,
    ) -> TradeDecision:
        """Confirm an observed breakout before allowing next-open entry."""

        if (
            not self.config.enable_volume_price_breakout_confirmation_entry
            or not decision.reason.startswith("volume_price_trial_entry")
        ):
            return decision
        confirmation_bars = max(1, self.config.volume_price_breakout_confirmation_bars)
        elapsed = confirmation_index - signal_index
        if elapsed < 1:
            return TradeDecision(
                side=None,
                reason=(
                    "volume_price_breakout_confirmation_wait: "
                    f"elapsed={elapsed} required=1; original={decision.reason}"
                ),
            )
        if elapsed > confirmation_bars:
            return _cancel_volume_breakout_confirmation(
                "confirmation_window_expired",
                decision,
                bars[signal_index],
                bars[confirmation_index],
                main_flow,
            )

        signal_bar = bars[signal_index]
        confirmation_bar = bars[confirmation_index]
        if confirmation_bar.low < signal_bar.low:
            return _cancel_volume_breakout_confirmation(
                "broke_signal_low",
                decision,
                signal_bar,
                confirmation_bar,
                main_flow,
            )
        if confirmation_bar.close < signal_bar.close:
            return _cancel_volume_breakout_confirmation(
                "closed_below_signal_close",
                decision,
                signal_bar,
                confirmation_bar,
                main_flow,
            )
        volume_state = _follow_through_volume_state(bars, confirmation_index)
        if volume_state in {"volume_down_risk", "high_volume_stall"}:
            return _cancel_volume_breakout_confirmation(
                f"weak_effort_result:{volume_state}",
                decision,
                signal_bar,
                confirmation_bar,
                main_flow,
            )
        if main_flow is not None and main_flow < 0:
            return _cancel_volume_breakout_confirmation(
                "main_flow_turned_negative",
                decision,
                signal_bar,
                confirmation_bar,
                main_flow,
            )
        return TradeDecision(
            side=decision.side,
            target_weight=decision.target_weight,
            reason=(
                f"{decision.reason}; volume_price_breakout_confirmation_entry: "
                f"original_signal={signal_bar.trade_date} "
                f"confirmation={confirmation_bar.trade_date} "
                f"signal_close={signal_bar.close:.2f} "
                f"confirm_close={confirmation_bar.close:.2f} "
                f"volume_state={volume_state} "
                f"main_flow={_fmt_optional(main_flow)}"
            ),
        )

    def should_add_pre_breakout_watch(
        self,
        context: VolumeProbeContext,
        broker: PaperBroker,
        symbol: str,
    ) -> bool:
        """Return whether a non-breakout node should enter the observation pool."""

        if not self.config.enable_volume_price_pre_breakout_watchlist_entry:
            return False
        position = broker.positions.get(symbol)
        if position is not None and position.quantity > 0:
            return False
        return (
            context.node.node_type
            in self.config.volume_price_pre_breakout_watch_node_types
        )

    def confirm_pre_breakout_watchlist_entry(
        self,
        *,
        symbol: str,
        watch_context: VolumeProbeContext,
        confirmation_context: VolumeProbeContext,
        bars: list[Bar],
        watch_index: int,
        confirmation_index: int,
        main_flow: float | None = None,
    ) -> TradeDecision:
        """Turn a watched node into a breakout trial only after confirmation."""

        if not self.config.enable_volume_price_pre_breakout_watchlist_entry:
            return TradeDecision(
                side=None,
                reason="volume_price_pre_breakout_watch_disabled",
            )
        age = confirmation_index - watch_index
        if age < 1:
            return TradeDecision(
                side=None,
                reason=f"volume_price_pre_breakout_watch_wait: age={age}",
            )
        max_age = max(1, self.config.volume_price_pre_breakout_max_age_bars)
        if age > max_age:
            return TradeDecision(
                side=None,
                reason=(
                    "volume_price_pre_breakout_watch_cancel: "
                    f"expired age={age} max_age={max_age} "
                    f"watch_node={watch_context.node.node_type}"
                ),
            )
        if confirmation_context.node.node_type != "volume_breakout":
            return TradeDecision(
                side=None,
                reason=(
                    "volume_price_pre_breakout_watch_hold: "
                    f"watch_node={watch_context.node.node_type} "
                    f"current_node={confirmation_context.node.node_type} age={age}"
                ),
            )

        watch_bar = bars[watch_index]
        confirmation_bar = bars[confirmation_index]
        price_stood = confirmation_bar.close >= watch_bar.close
        if not price_stood:
            return _cancel_pre_breakout_watch(
                "price_not_stood",
                watch_context,
                confirmation_context,
                age,
                main_flow,
            )
        volume_expanded = _is_confirmation_volume_expanded(bars, confirmation_index)
        if not volume_expanded:
            return _cancel_pre_breakout_watch(
                "volume_not_expanded",
                watch_context,
                confirmation_context,
                age,
                main_flow,
            )
        if (
            main_flow is None
            and not self.config.volume_price_pre_breakout_allow_unknown_flow
        ):
            return _cancel_pre_breakout_watch(
                "main_flow_unknown",
                watch_context,
                confirmation_context,
                age,
                main_flow,
            )
        if main_flow is not None and main_flow < 0:
            return _cancel_pre_breakout_watch(
                "main_flow_weak",
                watch_context,
                confirmation_context,
                age,
                main_flow,
            )

        tier, target_weight = _pre_breakout_position_tier(
            config=self.config,
            bars=bars,
            watch_index=watch_index,
            confirmation_index=confirmation_index,
            confirmation_context=confirmation_context,
            main_flow=main_flow,
        )
        target_weight = min(target_weight, self.config.max_single_position_weight)
        return TradeDecision(
            side=OrderSide.BUY,
            target_weight=target_weight,
            reason=(
                "volume_price_trial_entry: "
                f"node=volume_breakout "
                f"cases={confirmation_context.resolved_cases} "
                f"win={_fmt_optional(confirmation_context.win_rate_pct)}% "
                f"avg={_fmt_optional(confirmation_context.avg_return_pct)}%; "
                "pre_breakout_watchlist_entry: "
                f"symbol={symbol} "
                f"watch_node={watch_context.node.node_type} "
                f"watch_date={watch_context.as_of_date} "
                f"age={age} "
                f"price_stood={price_stood} "
                f"volume_expanded={volume_expanded} "
                f"main_flow={_fmt_optional(main_flow)} "
                f"tier={tier} "
                f"weight={target_weight * 100:.2f}%; "
                f"{confirmation_context.reason}"
            ),
        )

    def decide_volume_probe_exit(
        self,
        symbol: str,
        broker: PaperBroker,
        bars: list[Bar] | None = None,
        current_index: int | None = None,
        main_flow: float | None = None,
    ) -> TradeDecision:
        """Exit a volume-price trial when its follow-through thesis expires."""

        if (
            not self.config.enable_volume_price_probe
            or not self.config.enable_volume_price_timed_exit
        ):
            return TradeDecision(side=None, reason="volume_price_trial_exit_disabled")
        position = broker.positions.get(symbol)
        if position is None or position.quantity <= 0:
            return TradeDecision(side=None, reason="volume_price_trial_exit_blocked: flat")
        last_buy = _last_buy_fill(broker, symbol)
        if last_buy is None or not last_buy.reason.startswith("volume_price_trial_entry"):
            return TradeDecision(
                side=None,
                reason="volume_price_trial_exit_blocked: last_entry_not_volume_probe",
            )
        if self.config.enable_volume_price_follow_through_exit:
            return _volume_price_follow_through_exit_decision(
                config=self.config,
                last_buy=last_buy,
                broker=broker,
                symbol=symbol,
                bars=bars,
                current_index=current_index,
                main_flow=main_flow,
            )
        return TradeDecision(
            side=OrderSide.SELL,
            reason=(
                "volume_price_trial_exit: "
                f"entry_date={last_buy.trade_date} timed_next_eligible_open"
            ),
        )

    def confirm_volume_probe_opening(
        self,
        decision: TradeDecision,
        bars: list[Bar],
        signal_index: int,
        execution_index: int,
    ) -> TradeDecision:
        """Confirm or cancel a volume trial at the next open.

        The expected opening range is inferred from prior same-node samples with
        similar成交额 and volume behavior, then compared with the actual next open.
        """

        if (
            not self.config.enable_volume_price_probe
            or not self.config.enable_volume_price_opening_gate
            or not decision.reason.startswith("volume_price_trial_entry")
        ):
            return decision
        signal_bar = bars[signal_index]
        execution_bar = bars[execution_index]
        opening_config = self.volume_probe_opening_config()
        expectation = build_volume_probe_opening_expectation(
            bars=bars,
            signal_index=signal_index,
            execution_index=execution_index,
            config=opening_config,
        )
        gap_pct = expectation.actual_gap_pct
        if expectation.expected_gap_pct is None:
            return _cancel_volume_opening(
                "opening_expectation_insufficient_history",
                gap_pct,
                decision,
                expectation,
            )
        if self.config.require_open_above_signal_low and execution_bar.open <= signal_bar.low:
            return _cancel_volume_opening(
                "open_broke_signal_low",
                gap_pct,
                decision,
                expectation,
            )
        if (
            expectation.high_gap_pct is not None
            and gap_pct > expectation.high_gap_pct
        ):
            return _cancel_volume_opening(
                "opening_above_expected_range",
                gap_pct,
                decision,
                expectation,
            )
        if (
            expectation.expected_gap_pct is not None
            and expectation.node_type
            in {"shrink_pullback", "dry_up_base", "quiet_consolidation"}
            and gap_pct > expectation.expected_gap_pct + opening_config.min_band_width_pct
        ):
            return _cancel_volume_opening(
                "opening_above_expected_pullback_premium",
                gap_pct,
                decision,
                expectation,
            )
        below_expected = (
            expectation.low_gap_pct is not None
            and gap_pct < expectation.low_gap_pct
        )
        if (
            below_expected
            and "node=volume_breakout" in decision.reason
            and (
                signal_bar.change_pct is None
                or signal_bar.change_pct >= self.config.hot_breakout_change_pct
                or gap_pct < 0
            )
        ):
            return _cancel_volume_opening(
                "opening_below_expected_range_after_breakout",
                gap_pct,
                decision,
                expectation,
            )
        if (
            self.config.require_nonnegative_open_after_hot_breakout
            and "node=volume_breakout" in decision.reason
            and signal_bar.change_pct is not None
            and signal_bar.change_pct >= self.config.hot_breakout_change_pct
            and gap_pct < 0
            and expectation.expected_gap_pct is not None
            and expectation.expected_gap_pct >= 0
        ):
            return _cancel_volume_opening(
                "hot_breakout_failed_expected_positive_open",
                gap_pct,
                decision,
                expectation,
            )
        breakout_opening_block = _volume_price_breakout_opening_block_reason(
            decision=decision,
            signal_bar=signal_bar,
            execution_bar=execution_bar,
            gap_pct=gap_pct,
            config=self.config,
        )
        if breakout_opening_block is not None:
            return _cancel_volume_opening(
                breakout_opening_block,
                gap_pct,
                decision,
                expectation,
            )
        dry_up_opening_block = _volume_price_dry_up_opening_block_reason(
            decision=decision,
            signal_bar=signal_bar,
            execution_bar=execution_bar,
            gap_pct=gap_pct,
            config=self.config,
        )
        if dry_up_opening_block is not None:
            return _cancel_volume_opening(
                dry_up_opening_block,
                gap_pct,
                decision,
                expectation,
            )
        confirmed = _confirm_volume_opening(decision, expectation)
        return _apply_volume_price_risk_sizing(
            decision=confirmed,
            signal_bar=signal_bar,
            execution_bar=execution_bar,
            expectation=expectation,
            config=self.config,
        )

    def volume_probe_opening_config(self) -> OpeningExpectationConfig:
        """Return the dynamic next-open expectation config."""

        return OpeningExpectationConfig(
            window=self.config.volume_price_probe_window,
            min_cases=max(1, min(5, self.config.volume_price_probe_min_cases)),
        )

    def create_order(
        self,
        symbol: str,
        decision: TradeDecision,
        broker: PaperBroker,
        latest_prices: dict[str, float],
        execution_price: float,
    ) -> Order | None:
        """Create an executable order from a pending decision."""

        if decision.side is None:
            return None
        if decision.side == OrderSide.SELL:
            position = broker.positions.get(symbol)
            if not position or position.quantity <= 0:
                return None
            return Order(
                symbol=symbol,
                side=OrderSide.SELL,
                quantity=position.quantity,
                reason=decision.reason,
            )

        equity = broker.equity(latest_prices)
        target_value = equity * decision.target_weight
        current_position = broker.positions.get(symbol)
        current_value = (
            current_position.quantity * execution_price
            if current_position is not None
            else 0.0
        )
        cash_to_deploy = min(broker.cash, max(0.0, target_value - current_value))
        quantity = round_down_to_lot(int(cash_to_deploy / execution_price))
        if quantity <= 0:
            return None
        return Order(
            symbol=symbol,
            side=OrderSide.BUY,
            quantity=quantity,
            reason=decision.reason,
        )


def _is_breakout_entry(signal: StockSignal, config: DisciplineConfig) -> bool:
    if not (
        signal.fund_signal == FundSignal.BUY
        and PatternTag.VOLUME_BREAKOUT in signal.pattern_tags
    ):
        return False
    if (
        PatternTag.FAILED_BREAKOUT in signal.pattern_tags
        or PatternTag.SUSPECTED_DISTRIBUTION in signal.pattern_tags
    ):
        return False
    if not _entry_quality_allows(signal, config):
        return False
    profile = signal.intent_profile
    if profile is None:
        return True
    quote = signal.quote
    flow = signal.fund_flow
    if (
        profile.close_vs_vwap_60_pct is not None
        and profile.close_vs_vwap_60_pct > config.max_breakout_close_vs_vwap60_pct
    ):
        return False
    if (
        flow.turnover_rate is not None
        and flow.turnover_rate > config.max_breakout_turnover_rate
    ):
        return False
    if (
        quote is not None
        and quote.volume_ratio is not None
        and quote.volume_ratio >= 2.5
        and profile.weekly_trend != "up"
    ):
        return False
    return (
        profile.markup_score >= config.min_markup_score
        and profile.distribution_score <= config.max_distribution_entry_score
    )


def _is_accumulation_entry(signal: StockSignal, config: DisciplineConfig) -> bool:
    accumulation_tags = {
        PatternTag.SUSPECTED_ACCUMULATION,
        PatternTag.VCP_SETUP,
    }
    if not (
        signal.fund_signal == FundSignal.SUSPECTED_ACCUMULATION
        and bool(accumulation_tags.intersection(signal.pattern_tags))
    ):
        return False
    profile = signal.intent_profile
    if profile is None:
        return True
    if not _entry_quality_allows(signal, config):
        return False
    return (
        profile.accumulation_score >= config.min_accumulation_score
        and profile.distribution_score <= config.max_distribution_entry_score
    )


def _is_active_probe_entry(signal: StockSignal, config: DisciplineConfig) -> bool:
    if not config.enable_active_probe:
        return False
    if signal.fund_signal not in {FundSignal.BUY, FundSignal.SUSPECTED_ACCUMULATION}:
        return False
    if (
        PatternTag.FAILED_BREAKOUT in signal.pattern_tags
        or PatternTag.SUSPECTED_DISTRIBUTION in signal.pattern_tags
    ):
        return False

    quote = signal.quote
    flow = signal.fund_flow
    profile = signal.intent_profile
    if flow.main_net_inflow <= 0:
        return False
    if (
        flow.main_net_inflow_pct is None
        or flow.main_net_inflow_pct < config.min_pursuit_main_pct
    ):
        return False
    if flow.super_large_net_inflow < 0:
        return False
    if quote is not None and quote.change_pct is not None and quote.change_pct < -2.0:
        return False
    if (
        profile is not None
        and profile.distribution_score > config.max_pursuit_distribution_score
    ):
        return False
    if (
        quote is not None
        and quote.volume_ratio is not None
        and quote.volume_ratio >= 3.5
        and profile is not None
        and profile.weekly_trend != "up"
    ):
        return False

    tags = set(signal.pattern_tags)
    has_setup = bool(
        {
            PatternTag.VOLUME_BREAKOUT,
            PatternTag.VCP_SETUP,
            PatternTag.SUSPECTED_ACCUMULATION,
        }.intersection(tags)
    )
    if not has_setup:
        return False
    return _entry_quality_allows(signal, config, require_known=True)


def _is_pursuit_probe_entry(signal: StockSignal, config: DisciplineConfig) -> bool:
    if not config.enable_pursuit_probe:
        return False
    if signal.fund_signal != FundSignal.BUY:
        return False
    if (
        PatternTag.FAILED_BREAKOUT in signal.pattern_tags
        or PatternTag.SUSPECTED_DISTRIBUTION in signal.pattern_tags
    ):
        return False

    quote = signal.quote
    flow = signal.fund_flow
    profile = signal.intent_profile
    if (
        flow.main_net_inflow_pct is None
        or flow.main_net_inflow_pct < config.min_pursuit_main_pct
    ):
        return False
    if flow.super_large_net_inflow <= 0:
        return False
    if quote is not None and quote.change_pct is not None and quote.change_pct <= 0:
        return False
    if (
        profile is not None
        and profile.distribution_score > config.max_pursuit_distribution_score
    ):
        return False

    has_breakout = PatternTag.VOLUME_BREAKOUT in signal.pattern_tags
    has_volume = bool(
        quote is None
        or quote.volume_ratio is None
        or quote.volume_ratio >= config.min_pursuit_volume_ratio
    )
    return (has_breakout or has_volume) and _entry_quality_allows(signal, config)


def _entry_quality_allows(
    signal: StockSignal,
    config: DisciplineConfig,
    *,
    require_known: bool = False,
) -> bool:
    quality = estimate_entry_quality(signal, config.min_entry_reward_risk)
    if require_known and not quality.known:
        return False
    return quality.passed


def _volume_price_intent_block_reason(
    *,
    context: VolumeProbeContext,
    config: DisciplineConfig,
    intent_profile: MainForceProfile | None,
) -> str | None:
    """Return a conservative intent-filter block reason for trial buys."""

    if not config.enable_volume_price_intent_filter:
        return None
    if intent_profile is None:
        return None
    node_type = context.node.node_type
    if node_type == "volume_breakout":
        return None
    if (
        config.volume_price_block_non_breakout_markdown
        and intent_profile.stage == "markdown_risk"
    ):
        return (
            "intent_filter_markdown_risk:"
            f"stage={intent_profile.stage} "
            f"daily={intent_profile.daily_trend} "
            f"weekly={intent_profile.weekly_trend}"
        )
    if (
        node_type == "quiet_consolidation"
        and config.volume_price_block_quiet_weekly_down
        and intent_profile.weekly_trend == "down"
    ):
        if _volume_price_quiet_weekly_down_exception_allows(
            context=context,
            config=config,
            intent_profile=intent_profile,
        ):
            return None
        return (
            "intent_filter_quiet_weekly_down:"
            f"weekly={intent_profile.weekly_trend} "
            f"dist={intent_profile.distribution_score:.1f} "
            f"main_flow_10={_fmt_optional(intent_profile.main_flow_10)}"
        )
    close_vs_vwap60 = intent_profile.close_vs_vwap_60_pct
    if (
        node_type == "dry_up_base"
        and close_vs_vwap60 is not None
        and close_vs_vwap60 < config.volume_price_dry_up_min_close_vs_vwap60_pct
    ):
        return (
            "intent_filter_dry_up_far_below_vwap60:"
            f"close_vs_vwap60={close_vs_vwap60:.2f}% "
            f"min={config.volume_price_dry_up_min_close_vs_vwap60_pct:.2f}%"
        )
    return None


def _volume_price_quiet_weekly_down_exception_allows(
    *,
    context: VolumeProbeContext,
    config: DisciplineConfig,
    intent_profile: MainForceProfile,
) -> bool:
    """Allow a quiet weekly-down trial only from point-in-time context stats."""

    if not config.enable_volume_price_quiet_weekly_down_exception:
        return False
    if (
        context.resolved_cases
        < config.volume_price_quiet_weekly_down_exception_min_cases
    ):
        return False
    win_rate = context.win_rate_pct
    if (
        win_rate is None
        or win_rate
        < config.volume_price_quiet_weekly_down_exception_min_win_rate_pct
    ):
        return False
    avg_return = context.avg_return_pct
    if (
        avg_return is None
        or avg_return
        < config.volume_price_quiet_weekly_down_exception_min_avg_return_pct
    ):
        return False
    if config.enable_volume_price_quiet_weekly_down_exception_flow_guard:
        min_main_flow_10 = (
            config.volume_price_quiet_weekly_down_exception_min_main_flow_10
        )
        if intent_profile.main_flow_10 is None:
            return False
        if (
            min_main_flow_10 is not None
            and intent_profile.main_flow_10 < min_main_flow_10
        ):
            return False
    return (
        intent_profile.distribution_score
        <= config.volume_price_quiet_weekly_down_exception_max_distribution_score
    )


def _volume_price_main_force_profile_block_reason(
    *,
    config: DisciplineConfig,
    intent_profile: MainForceProfile | None,
) -> str | None:
    """Return a block reason for the main-force profile research filter."""

    if not config.enable_volume_price_main_force_profile_filter:
        return None
    if intent_profile is None:
        return "main_force_profile_filter_missing_profile"
    if intent_profile.stage not in config.volume_price_main_force_allowed_stages:
        return (
            "main_force_profile_filter_stage:"
            f"stage={intent_profile.stage}"
        )
    max_distribution = config.volume_price_main_force_max_distribution_score
    if (
        max_distribution is not None
        and intent_profile.distribution_score > max_distribution
    ):
        return (
            "main_force_profile_filter_distribution:"
            f"dist={intent_profile.distribution_score:.1f} "
            f"max={max_distribution:.1f}"
        )
    if config.volume_price_main_force_require_positive_flow_majority:
        flows = [
            item
            for item in (
                intent_profile.main_flow_3,
                intent_profile.main_flow_5,
                intent_profile.main_flow_10,
            )
            if item is not None
        ]
        if not flows:
            return "main_force_profile_filter_missing_flow_window"
        positive = sum(item >= 0 for item in flows)
        if positive <= len(flows) / 2:
            return (
                "main_force_profile_filter_flow_not_positive:"
                f"positive={positive}/{len(flows)}"
            )
    return None


def _volume_price_weak_main_force_block_reason(
    *,
    config: DisciplineConfig,
    intent_profile: MainForceProfile | None,
) -> str | None:
    """Block only the broad-pool profile combinations with clear weak evidence."""

    if not config.enable_volume_price_weak_main_force_block:
        return None
    if intent_profile is None:
        return None
    if intent_profile.stage in config.volume_price_weak_main_force_block_stages:
        return f"weak_main_force_block_stage:stage={intent_profile.stage}"
    max_distribution = config.volume_price_weak_main_force_distribution_score
    if (
        max_distribution is not None
        and intent_profile.distribution_score >= max_distribution
    ):
        return (
            "weak_main_force_block_distribution:"
            f"dist={intent_profile.distribution_score:.1f} "
            f"max={max_distribution:.1f}"
        )
    flows = [
        item
        for item in (
            intent_profile.main_flow_3,
            intent_profile.main_flow_5,
            intent_profile.main_flow_10,
        )
        if item is not None
    ]
    negative = sum(item < 0 for item in flows)
    min_negative = max(1, config.volume_price_weak_main_force_min_negative_flow_windows)
    if negative >= min_negative:
        return (
            "weak_main_force_block_negative_flow:"
            f"negative={negative}/{len(flows)}"
        )
    return None


def _volume_price_support_quality_block_reason(
    *,
    context: VolumeProbeContext,
    config: DisciplineConfig,
    intent_profile: MainForceProfile | None,
) -> str | None:
    """Return a support-quality block reason for low-edge trial nodes."""

    if not config.enable_volume_price_support_quality_filter:
        return None
    node_type = context.node.node_type
    if node_type != "dry_up_base":
        return None
    if (
        config.volume_price_block_dry_up_without_main_flow
        and (
            intent_profile is None
            or intent_profile.main_flow_5 is None
            or intent_profile.main_flow_5 < 0
        )
    ):
        main_flow = None if intent_profile is None else intent_profile.main_flow_5
        return (
            "support_quality_dry_up_missing_or_negative_main_flow:"
            f"main_flow_5={_fmt_optional(main_flow)}"
        )
    avg_return = context.avg_return_pct
    if (
        avg_return is None
        or avg_return
        < config.volume_price_support_quality_min_dry_up_avg_return_pct
    ):
        return (
            "support_quality_dry_up_low_edge:"
            f"avg={_fmt_optional(avg_return)}% "
            f"min={config.volume_price_support_quality_min_dry_up_avg_return_pct:.2f}%"
        )
    return None


def _volume_price_dry_up_block_reason(
    *,
    context: VolumeProbeContext,
    config: DisciplineConfig,
    intent_profile: MainForceProfile | None,
) -> str | None:
    """Return a phase/flow block reason for dry-up base trial buys."""

    if not config.enable_volume_price_dry_up_guard:
        return None
    if context.node.node_type != "dry_up_base":
        return None
    if intent_profile is None:
        return "dry_up_guard_missing_intent_profile"
    if intent_profile.stage in config.volume_price_dry_up_block_stages:
        return (
            "dry_up_guard_blocked_stage:"
            f"stage={intent_profile.stage}"
        )
    if intent_profile.weekly_trend in config.volume_price_dry_up_block_weekly_trends:
        return (
            "dry_up_guard_blocked_weekly_trend:"
            f"weekly={intent_profile.weekly_trend}"
        )
    max_distribution = config.volume_price_dry_up_max_distribution_score
    if (
        max_distribution is not None
        and intent_profile.distribution_score > max_distribution
    ):
        return (
            "dry_up_guard_distribution_risk:"
            f"dist={intent_profile.distribution_score:.1f} "
            f"max={max_distribution:.1f}"
        )
    if (
        config.volume_price_dry_up_require_nonnegative_main_flow_10
        and intent_profile.main_flow_10 is not None
        and intent_profile.main_flow_10 < 0
    ):
        return (
            "dry_up_guard_negative_main_flow_10:"
            f"main_flow_10={_fmt_optional(intent_profile.main_flow_10)}"
        )
    return None


def _volume_price_node_quality_block_reason(
    *,
    context: VolumeProbeContext,
    config: DisciplineConfig,
    intent_profile: MainForceProfile | None,
) -> str | None:
    """Return a block reason for expanded non-dry-up volume-price nodes."""

    if not config.enable_volume_price_node_quality_filter:
        return None
    node_type = context.node.node_type
    if node_type not in config.volume_price_node_quality_node_types:
        return None
    avg_return = context.avg_return_pct
    if (
        avg_return is None
        or avg_return < config.volume_price_node_quality_min_avg_return_pct
    ):
        return (
            "node_quality_low_edge:"
            f"avg={_fmt_optional(avg_return)}% "
            f"min={config.volume_price_node_quality_min_avg_return_pct:.2f}%"
        )
    win_rate = context.win_rate_pct
    if (
        win_rate is None
        or win_rate < config.volume_price_node_quality_min_win_rate_pct
    ):
        return (
            "node_quality_low_win_rate:"
            f"win={_fmt_optional(win_rate)}% "
            f"min={config.volume_price_node_quality_min_win_rate_pct:.2f}%"
        )
    if intent_profile is None:
        return "node_quality_missing_intent_profile"

    min_main_flow_5 = config.volume_price_node_quality_min_main_flow_5
    if (
        min_main_flow_5 is not None
        and (
            intent_profile.main_flow_5 is None
            or intent_profile.main_flow_5 < min_main_flow_5
        )
    ):
        return (
            "node_quality_weak_main_flow:"
            f"main_flow_5={_fmt_optional(intent_profile.main_flow_5)} "
            f"min={min_main_flow_5:.2f}"
        )
    if (
        config.volume_price_node_quality_allowed_daily_trends
        and intent_profile.daily_trend
        not in config.volume_price_node_quality_allowed_daily_trends
    ):
        return (
            "node_quality_weak_daily_trend:"
            f"daily={intent_profile.daily_trend}"
        )
    if (
        config.volume_price_node_quality_allowed_weekly_trends
        and intent_profile.weekly_trend
        not in config.volume_price_node_quality_allowed_weekly_trends
    ):
        return (
            "node_quality_weak_weekly_trend:"
            f"weekly={intent_profile.weekly_trend}"
        )
    if intent_profile.stage in config.volume_price_node_quality_block_stages:
        return (
            "node_quality_blocked_stage:"
            f"stage={intent_profile.stage}"
        )
    max_distribution = config.volume_price_node_quality_max_distribution_score
    if (
        max_distribution is not None
        and intent_profile.distribution_score > max_distribution
    ):
        return (
            "node_quality_distribution_risk:"
            f"dist={intent_profile.distribution_score:.1f} "
            f"max={max_distribution:.1f}"
        )
    return None


def _volume_price_dry_up_opening_block_reason(
    *,
    decision: TradeDecision,
    signal_bar: Bar,
    execution_bar: Bar,
    gap_pct: float,
    config: DisciplineConfig,
) -> str | None:
    """Return an execution-time block reason for dry-up support quality."""

    if not config.enable_volume_price_dry_up_guard:
        return None
    if "node=dry_up_base" not in decision.reason:
        return None
    if execution_bar.open <= 0:
        return None
    support_distance_pct = (execution_bar.open - signal_bar.low) / execution_bar.open * 100
    min_support = config.volume_price_dry_up_min_support_distance_pct
    if min_support is not None and support_distance_pct < min_support:
        return (
            "dry_up_support_distance_too_close "
            f"support_distance={support_distance_pct:.2f}% "
            f"min={min_support:.2f}%"
        )
    max_support = config.volume_price_dry_up_max_support_distance_pct
    if max_support is not None and support_distance_pct > max_support:
        return (
            "dry_up_support_distance_too_wide "
            f"support_distance={support_distance_pct:.2f}% "
            f"max={max_support:.2f}%"
        )
    max_gap = config.volume_price_dry_up_max_opening_gap_pct
    if max_gap is not None and gap_pct > max_gap:
        return (
            "dry_up_opening_gap_too_high "
            f"gap={gap_pct:.2f}% max={max_gap:.2f}%"
        )
    return None


def _volume_price_breakout_opening_block_reason(
    *,
    decision: TradeDecision,
    signal_bar: Bar,
    execution_bar: Bar,
    gap_pct: float,
    config: DisciplineConfig,
) -> str | None:
    """Return an execution-time block reason for risky breakout openings."""

    if "node=volume_breakout" not in decision.reason:
        return None
    if execution_bar.open <= 0 or signal_bar.low <= 0:
        return None
    max_gap = config.volume_price_breakout_max_opening_gap_pct
    if max_gap is not None and gap_pct > max_gap:
        return f"breakout_opening_gap_too_high max={max_gap:.2f}%"
    wide_support = config.volume_price_breakout_wide_support_distance_pct
    min_gap = config.volume_price_breakout_min_gap_for_wide_support_pct
    if wide_support is None or min_gap is None:
        return None
    support_distance_pct = (execution_bar.open - signal_bar.low) / execution_bar.open * 100
    if support_distance_pct > wide_support and gap_pct < min_gap:
        return (
            "breakout_wide_support_without_opening_demand "
            f"support_distance={support_distance_pct:.2f}% "
            f"max_support={wide_support:.2f}% min_gap={min_gap:.2f}%"
        )
    return None


def _apply_volume_price_risk_sizing(
    *,
    decision: TradeDecision,
    signal_bar: Bar,
    execution_bar: Bar,
    expectation: OpeningExpectation,
    config: DisciplineConfig,
) -> TradeDecision:
    """Size a volume-price trial by account risk and signal-day support."""

    if not config.enable_volume_price_risk_sizing or decision.side != OrderSide.BUY:
        return decision
    entry_price = execution_bar.open
    support = signal_bar.low
    if entry_price <= 0 or support <= 0 or entry_price <= support:
        return TradeDecision(
            side=None,
            reason=(
                "volume_price_opening_cancel: invalid_risk_support "
                f"entry={entry_price:.2f} support={support:.2f}; "
                f"original={decision.reason}"
            ),
        )
    raw_stop_distance_pct = (entry_price - support) / entry_price
    if (
        config.volume_price_min_raw_stop_upsize_pct > 0
        and raw_stop_distance_pct < config.volume_price_min_raw_stop_upsize_pct
    ):
        target_weight = min(decision.target_weight, config.max_single_position_weight)
        if target_weight <= 0:
            return TradeDecision(
                side=None,
                reason=(
                    "volume_price_opening_cancel: raw_stop_base_weight_zero "
                    f"raw_stop={raw_stop_distance_pct * 100:.2f}%; "
                    f"original={decision.reason}"
                ),
            )
        return TradeDecision(
            side=decision.side,
            target_weight=target_weight,
            reason=(
                f"{decision.reason}; volume_price_support_base_weight: "
                f"support={support:.2f} "
                f"raw_stop={raw_stop_distance_pct * 100:.2f}% "
                f"min_upsize={config.volume_price_min_raw_stop_upsize_pct * 100:.2f}% "
                f"weight={target_weight * 100:.2f}%"
            ),
        )
    sizing_stop_distance_pct = max(
        raw_stop_distance_pct,
        config.volume_price_min_stop_distance_pct,
    )
    if (
        sizing_stop_distance_pct <= 0
        or config.volume_price_account_risk_pct <= 0
        or config.volume_price_risk_sizing_max_weight <= 0
    ):
        return TradeDecision(
            side=None,
            reason=(
                "volume_price_opening_cancel: invalid_risk_budget "
                f"account_risk={config.volume_price_account_risk_pct:.4f} "
                f"stop_distance={sizing_stop_distance_pct:.4f}; "
                f"original={decision.reason}"
            ),
        )
    risk_weight = config.volume_price_account_risk_pct / sizing_stop_distance_pct
    weight_caps = [
        risk_weight,
        config.volume_price_risk_sizing_max_weight,
        config.max_single_position_weight,
    ]
    if config.volume_price_risk_sizing_respects_decision_cap:
        weight_caps.append(decision.target_weight)
    target_weight = min(weight_caps)
    if expectation.classification != "expected_open":
        target_weight *= config.volume_price_uncertain_open_weight_factor
    if target_weight <= 0:
        return TradeDecision(
            side=None,
            reason=(
                "volume_price_opening_cancel: risk_sized_weight_zero "
                f"entry={entry_price:.2f} support={support:.2f}; "
                f"original={decision.reason}"
            ),
        )
    return TradeDecision(
        side=decision.side,
        target_weight=target_weight,
        reason=(
            f"{decision.reason}; volume_price_risk_sized: "
            f"support={support:.2f} "
            f"raw_stop={raw_stop_distance_pct * 100:.2f}% "
            f"sizing_stop={sizing_stop_distance_pct * 100:.2f}% "
            f"account_risk={config.volume_price_account_risk_pct * 100:.2f}% "
            f"weight={target_weight * 100:.2f}%"
        ),
    )


def _cancel_pre_breakout_watch(
    reason: str,
    watch_context: VolumeProbeContext,
    confirmation_context: VolumeProbeContext,
    age: int,
    main_flow: float | None,
) -> TradeDecision:
    return TradeDecision(
        side=None,
        reason=(
            "volume_price_pre_breakout_watch_cancel: "
            f"{reason} watch_node={watch_context.node.node_type} "
            f"confirm_node={confirmation_context.node.node_type} "
            f"age={age} main_flow={_fmt_optional(main_flow)}"
        ),
    )


def _is_confirmation_volume_expanded(bars: list[Bar], index: int) -> bool:
    if index <= 0:
        return False
    history = bars[max(0, index - 5):index]
    volumes = [bar.volume for bar in history if bar.volume > 0]
    if not volumes:
        return False
    return bars[index].volume >= (sum(volumes) / len(volumes)) * 1.2


def _pre_breakout_position_tier(
    *,
    config: DisciplineConfig,
    bars: list[Bar],
    watch_index: int,
    confirmation_index: int,
    confirmation_context: VolumeProbeContext,
    main_flow: float | None,
) -> tuple[str, float]:
    confirmation_bar = bars[confirmation_index]
    previous_bar = bars[confirmation_index - 1] if confirmation_index > 0 else None
    continuous_price = (
        confirmation_index - watch_index >= 2
        and previous_bar is not None
        and previous_bar.close >= bars[watch_index].close
        and confirmation_bar.close >= previous_bar.close
    )
    positive_flow = main_flow is not None and main_flow >= 0
    if continuous_price and positive_flow:
        return (
            "continuous_confirmation",
            config.volume_price_pre_breakout_continuous_weight,
        )
    if confirmation_context.passed or positive_flow:
        return "strong_breakout_confirmation", config.volume_price_pre_breakout_strong_weight
    return "observation_confirmation", config.volume_price_pre_breakout_observation_weight


def _volume_price_follow_through_exit_decision(
    *,
    config: DisciplineConfig,
    last_buy: Fill,
    broker: PaperBroker,
    symbol: str,
    bars: list[Bar] | None,
    current_index: int | None,
    main_flow: float | None,
) -> TradeDecision:
    """Hold a breakout trial only while post-entry evidence confirms it."""

    if bars is None or current_index is None:
        return TradeDecision(
            side=None,
            reason="volume_price_follow_through_exit_blocked: missing_bar_context",
        )
    position = broker.positions.get(symbol)
    if position is None or position.quantity <= 0:
        return TradeDecision(side=None, reason="volume_price_trial_exit_blocked: flat")
    buy_index = _bar_index_by_date(bars, last_buy.trade_date)
    if buy_index is None or current_index < buy_index:
        return TradeDecision(
            side=None,
            reason="volume_price_follow_through_exit_blocked: missing_entry_bar",
        )
    evidence = _volume_price_follow_through_evidence(
        bars=bars,
        buy_index=buy_index,
        current_index=current_index,
        entry_price=last_buy.price,
        support=_volume_price_support(last_buy.reason, last_buy.price, config),
    )
    detail = (
        f"entry_date={last_buy.trade_date} hold_bars={evidence['hold_bars']} "
        f"support={evidence['support']:.2f} confirmations={evidence['confirmations']} "
        f"warnings={evidence['warnings']} invalidations={evidence['invalidations']}"
    )
    if (
        config.volume_price_follow_through_exit_on_negative_main_flow
        and main_flow is not None
        and main_flow < 0
    ):
        return TradeDecision(
            side=OrderSide.SELL,
            reason=(
                "volume_price_follow_through_exit: main_flow_weak "
                f"{detail} main_flow={main_flow:.2f}"
            ),
        )
    if evidence["invalidations"] > 0:
        return TradeDecision(
            side=OrderSide.SELL,
            reason=f"volume_price_follow_through_exit: invalidated {detail}",
        )
    current_bar = bars[current_index]
    current_volume_state = _follow_through_volume_state(bars, current_index)
    if (
        config.volume_price_follow_through_exit_on_profitable_stall
        and current_bar.close > last_buy.price
        and current_volume_state == "high_volume_stall"
    ):
        return TradeDecision(
            side=OrderSide.SELL,
            reason=(
                "volume_price_follow_through_exit: profitable_high_volume_stall "
                f"{detail} close={current_bar.close:.2f} entry={last_buy.price:.2f}"
            ),
        )
    no_confirm_bars = max(1, config.volume_price_follow_through_no_confirm_bars)
    first_bar_reference = (
        bars[buy_index - 1].close if buy_index > 0 else min(last_buy.price, position.avg_cost)
    )
    if (
        config.volume_price_follow_through_first_bar_exit_requires_loss
        and evidence["hold_bars"] <= 1
        and current_bar.close >= first_bar_reference
    ):
        return TradeDecision(
            side=None,
            reason=(
                "volume_price_follow_through_hold: first_bar_profitable_trial "
                f"{detail} close={current_bar.close:.2f} entry={last_buy.price:.2f} "
                f"avg_cost={position.avg_cost:.2f} reference={first_bar_reference:.2f}"
            ),
        )
    if (
        evidence["hold_bars"] >= no_confirm_bars
        and evidence["confirmations"] <= evidence["warnings"]
    ):
        return TradeDecision(
            side=OrderSide.SELL,
            reason=f"volume_price_follow_through_exit: no_follow_through {detail}",
        )
    max_hold_bars = max(no_confirm_bars, config.volume_price_follow_through_max_hold_bars)
    if evidence["hold_bars"] >= max_hold_bars:
        return TradeDecision(
            side=OrderSide.SELL,
            reason=f"volume_price_follow_through_exit: max_hold {detail}",
        )
    return TradeDecision(
        side=None,
        reason=f"volume_price_follow_through_hold: {detail}",
    )


def _volume_price_follow_through_evidence(
    *,
    bars: list[Bar],
    buy_index: int,
    current_index: int,
    entry_price: float,
    support: float,
) -> dict[str, float | int]:
    confirmations = 0
    warnings = 0
    invalidations = 0
    for index in range(buy_index, current_index + 1):
        bar = bars[index]
        volume_state = _follow_through_volume_state(bars, index)
        if bar.close < support:
            invalidations += 1
            continue
        if bar.low < support:
            warnings += 1
            continue
        change_pct = bar.change_pct or 0.0
        if volume_state in {"volume_down_risk", "high_volume_stall"}:
            warnings += 1
        elif (
            volume_state == "volume_confirmation"
            or bar.close > entry_price
            or (volume_state == "quiet_hold" and bar.close >= support)
        ):
            confirmations += 1
        elif bar.close < entry_price and change_pct < 0:
            warnings += 1
    return {
        "hold_bars": current_index - buy_index + 1,
        "support": support,
        "confirmations": confirmations,
        "warnings": warnings,
        "invalidations": invalidations,
    }


def _follow_through_volume_state(bars: list[Bar], index: int) -> str:
    if index <= 0:
        return "no_prior_volume"
    previous = bars[max(0, index - 5):index]
    average_volume = sum(item.volume for item in previous) / len(previous)
    ratio = bars[index].volume / average_volume if average_volume else 0.0
    change_pct = bars[index].change_pct or 0.0
    if ratio >= 1.5 and change_pct <= -2.0:
        return "volume_down_risk"
    if ratio >= 1.8 and change_pct <= 0.5:
        return "high_volume_stall"
    if ratio >= 1.5 and change_pct > 0.5:
        return "volume_confirmation"
    if ratio <= 0.7 and change_pct >= -1.0:
        return "quiet_hold"
    return "normal"


def _volume_price_support(
    reason: str,
    entry_price: float,
    config: DisciplineConfig,
) -> float:
    match = re.search(r"support=([0-9]+(?:\.[0-9]+)?)", reason)
    if match:
        return float(match.group(1))
    return entry_price * (1 - config.stop_loss_pct)


def _is_accumulation_proof_probe_entry(
    proof_context: AccumulationProofContext | None,
    config: DisciplineConfig,
) -> bool:
    if not config.enable_accumulation_proof_probe:
        return False
    if proof_context is None:
        return False
    return (
        proof_context.seed.is_candidate
        and proof_context.resolved >= config.min_accumulation_proof_cases
        and proof_context.confirmation_rate_pct is not None
        and proof_context.confirmation_rate_pct >= config.min_accumulation_proof_rate_pct
    )


def _is_exit_signal(signal: StockSignal) -> bool:
    return (
        signal.fund_signal
        in {FundSignal.SELL, FundSignal.SUSPECTED_DISTRIBUTION}
        or PatternTag.SUSPECTED_DISTRIBUTION in signal.pattern_tags
        or PatternTag.FAILED_BREAKOUT in signal.pattern_tags
    )


def _tags(signal: StockSignal) -> str:
    return ",".join(tag.value for tag in signal.pattern_tags)


def _fmt_optional(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}"


def _cancel_volume_opening(
    reason: str,
    gap_pct: float,
    original: TradeDecision,
    expectation: OpeningExpectation | None = None,
) -> TradeDecision:
    return TradeDecision(
        side=None,
        reason=(
            "volume_price_opening_cancel: "
            f"{reason} gap={gap_pct:.2f}%"
            f"{_opening_expectation_detail(expectation)}; "
            f"original={original.reason}"
        ),
    )


def _cancel_volume_breakout_confirmation(
    reason: str,
    original: TradeDecision,
    signal_bar: Bar,
    confirmation_bar: Bar,
    main_flow: float | None,
) -> TradeDecision:
    return TradeDecision(
        side=None,
        reason=(
            "volume_price_breakout_confirmation_cancel: "
            f"{reason} original_signal={signal_bar.trade_date} "
            f"confirmation={confirmation_bar.trade_date} "
            f"signal_low={signal_bar.low:.2f} "
            f"signal_close={signal_bar.close:.2f} "
            f"confirm_low={confirmation_bar.low:.2f} "
            f"confirm_close={confirmation_bar.close:.2f} "
            f"main_flow={_fmt_optional(main_flow)}; "
            f"original={original.reason}"
        ),
    )


def _confirm_volume_opening(
    original: TradeDecision,
    expectation: OpeningExpectation,
) -> TradeDecision:
    return TradeDecision(
        side=original.side,
        target_weight=original.target_weight,
        reason=(
            f"{original.reason}; volume_price_opening_confirmed: "
            f"gap={expectation.actual_gap_pct:.2f}%"
            f"{_opening_expectation_detail(expectation)}"
        ),
    )


def _opening_expectation_detail(expectation: OpeningExpectation | None) -> str:
    if expectation is None or expectation.expected_gap_pct is None:
        if expectation is None:
            return ""
        return (
            f" expected=- range=- cases={expectation.sample_cases} "
            f"class={expectation.classification}"
        )
    return (
        f" expected={expectation.expected_gap_pct:.2f}% "
        f"range={expectation.low_gap_pct:.2f}%..{expectation.high_gap_pct:.2f}% "
        f"cases={expectation.sample_cases} class={expectation.classification}"
    )


def _last_buy_fill(broker: PaperBroker, symbol: str) -> Fill | None:
    for fill in reversed(broker.fills):
        if fill.symbol == symbol and fill.side == OrderSide.BUY:
            return fill
    return None


def _bar_index_by_date(bars: list[Bar], trade_date: object) -> int | None:
    for index, bar in enumerate(bars):
        if bar.trade_date == trade_date:
            return index
    return None
