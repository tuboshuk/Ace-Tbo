"""Persistent replay training and parameter sweep helpers."""

from __future__ import annotations

from collections import Counter
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timezone, timedelta
import json
from pathlib import Path
from typing import Iterable

from wealth_lab.behavior_model import build_trading_state_model
from wealth_lab.diagnostics import (
    KnowledgeHypothesisReview,
    PositionActionReview,
    TradeStory,
    diagnose_replay,
)
from wealth_lab.fund_collector import EfinanceFundCollector
from wealth_lab.models import Bar, FundFlowSnapshot
from wealth_lab.performance import RoundTrip, estimate_returns
from wealth_lab.providers.historical_provider import (
    BaoStockHistoricalProvider,
    EfinanceHistoricalProvider,
)
from wealth_lab.replay import HistoricalReplayRunner, ReplayDecision, ReplayResult
from wealth_lab.target_graph import assess_target_return
from wealth_lab.trade_discipline import (
    DisciplineConfig,
    TradeDiscipline,
    discipline_config_for_mode,
)


PROMOTION_MIN_CLOSED_TRADES = 30
PROMOTION_MIN_TRADED_SYMBOLS = 2
PROMOTION_MIN_NET_EXPECTANCY_PCT = 0.50
PROMOTION_MIN_HOLDING_UTILIZATION_PCT = 1.00
PROMOTION_MIN_AVG_POSITION_PCT = 0.10
PROMOTION_DEFAULT_TARGET_RETURN_PCT = 10.00
CORE_CANDIDATE_NAMES = frozenset(
    {"volume_price_breakout_opening_guard_probe"}
)
LOSS_ATTRIBUTION_LIMIT = 12
FILTER_ATTRIBUTION_LIMIT = 80
MISSED_BIG_MOVE_HORIZON_BARS = 5
MISSED_BIG_MOVE_RETURN_PCT = 10.0
MISSED_OPPORTUNITY_DETAIL_LIMIT = 80
MISSED_OPPORTUNITY_PER_RESULT_LIMIT = 12
MISSED_OPPORTUNITY_DETAIL_CANDIDATES = frozenset(
    {"volume_price_breakout_opening_guard_probe"}
)


@dataclass(frozen=True)
class TrainingCandidate:
    """One paper-trading discipline configuration to test."""

    name: str
    skill_lenses: tuple[str, ...]
    hypothesis: str
    config: DisciplineConfig
    tier: str = "experimental"


@dataclass(frozen=True)
class LossAttribution:
    """Aggregate attribution for losing closed trades in one replay result."""

    symbol: str
    entry_reason: str
    volume_node: str
    trades: int
    avg_loss_return_pct: float
    total_pnl: float
    worst_return_pct: float


@dataclass(frozen=True)
class FilterAttribution:
    """Aggregate count for a buy signal blocked by one condition."""

    reason: str
    count: int


@dataclass(frozen=True)
class MissedOpportunity:
    """One flat day before a large forward move that was not actually bought."""

    symbol: str
    signal_date: str
    close: float
    next_1d_close_return_pct: float | None
    next_3d_close_return_pct: float | None
    next_5d_close_return_pct: float | None
    max_forward_return_pct: float
    max_forward_date: str
    max_forward_drawdown_pct: float
    attribution: str
    detail_reason: str
    volume_node: str
    volume_probe_passed: bool | None


@dataclass(frozen=True)
class CandidateResult:
    """Evaluation result for one candidate on one symbol."""

    run_id: str
    candidate: str
    symbol: str
    skill_lenses: tuple[str, ...]
    hypothesis: str
    bars_count: int
    fund_flows_count: int
    missing_fund_flow_dates: int
    fills: int
    closed_round_trips: int
    sample_quality: str
    final_value: float
    total_return_pct: float
    max_drawdown_pct: float
    expectancy_pct: float | None
    account_expectancy_pct: float | None
    profit_factor: float | None
    target_conclusion: str
    evidence_score: float
    trading_mode: str
    behavior_phase: str
    fund_flow_bias: str
    buy_state: str
    sell_state: str
    candidate_tier: str = "experimental"
    holding_days: int = 0
    cash_days: int = 0
    avg_position_pct: float = 0.0
    max_position_pct: float = 0.0
    buy_signal_count: int = 0
    filtered_buy_signals: int = 0
    raw_filtered_observations: int = 0
    ordinary_non_signal_days: int = 0
    top_filter_reason: str = "-"
    top_filter_count: int = 0
    filter_attributions: tuple[FilterAttribution, ...] = ()
    missed_big_moves: int = 0
    missed_big_moves_filtered: int = 0
    missed_big_moves_ordinary_non_signal: int = 0
    missed_big_moves_unrecognized: int = 0
    top_missed_big_move_reason: str = "-"
    missed_opportunity_attributions: tuple[FilterAttribution, ...] = ()
    missed_opportunities: tuple[MissedOpportunity, ...] = ()
    loss_attributions: tuple[LossAttribution, ...] = ()
    trade_stories: tuple[TradeStory, ...] = ()
    position_action_reviews: tuple[PositionActionReview, ...] = ()
    knowledge_hypothesis_reviews: tuple[KnowledgeHypothesisReview, ...] = ()


@dataclass(frozen=True)
class TrainingError:
    """Fetch or replay error captured without aborting the whole run."""

    run_id: str
    symbol: str
    message: str


@dataclass(frozen=True)
class TrainingRun:
    """A persisted training run."""

    run_id: str
    created_at: str
    symbols: tuple[str, ...]
    days: int
    initial_cash: float
    target_annual_return: float
    candidates: tuple[str, ...]
    results: tuple[CandidateResult, ...]
    errors: tuple[TrainingError, ...]
    jsonl_path: Path
    summary_path: Path
    pool_source: str = "manual"
    pool_seed: int | None = None
    pool_eligible_symbols: int | None = None
    missed_report_path: Path | None = None
    processed_symbols: int | None = None
    is_partial: bool = False


class TrainingHistoricalBarFetcher:
    """Fetch historical bars while avoiding repeated known-bad provider calls."""

    def __init__(self, *, efinance_disable_after_failures: int = 2) -> None:
        self._efinance = EfinanceHistoricalProvider()
        self._baostock = BaoStockHistoricalProvider(keep_session=True)
        self._efinance_failures = 0
        self._efinance_disable_after_failures = efinance_disable_after_failures

    def fetch_daily_bars(self, symbol: str, start: date, end: date) -> list[Bar]:
        errors: list[str] = []
        if self._efinance_failures < self._efinance_disable_after_failures:
            try:
                bars = self._efinance.fetch_daily_bars(symbol, start, end)
                if bars:
                    return bars
                self._efinance_failures += 1
                errors.append("efinance: empty result")
            except Exception as exc:  # noqa: BLE001 - provider exceptions vary.
                self._efinance_failures += 1
                errors.append(f"efinance: {exc}")
        else:
            errors.append("efinance: skipped after repeated training failures")

        try:
            bars = self._baostock.fetch_daily_bars(symbol, start, end)
            if bars:
                return bars
            errors.append("baostock: empty result")
        except Exception as exc:  # noqa: BLE001 - provider exceptions vary.
            errors.append(f"baostock: {exc}")
        raise RuntimeError("all historical bar providers failed: " + "; ".join(errors))

    def close(self) -> None:
        """Release provider sessions kept for a training run."""

        self._baostock.close()


def default_training_candidates() -> tuple[TrainingCandidate, ...]:
    """Return the single active training strategy."""

    for candidate in _legacy_training_candidates():
        if candidate.name == "volume_price_breakout_opening_guard_probe":
            return (replace(candidate, tier="core"),)
    raise RuntimeError("active training candidate is not registered")


def _legacy_training_candidates() -> tuple[TrainingCandidate, ...]:
    """Return archived research configs kept for old-run comparison.

    The names describe research lenses only. They are not claims that the
    external skills are installed or that any investor can be replicated.
    """

    quiet_exception_config = replace(
        discipline_config_for_mode("volume-probe"),
        enable_volume_price_intent_filter=True,
        enable_volume_price_support_quality_filter=True,
        volume_price_block_dry_up_without_main_flow=True,
        volume_price_support_quality_min_dry_up_avg_return_pct=0.35,
        volume_price_block_non_breakout_markdown=False,
        enable_volume_price_risk_sizing=True,
        volume_price_account_risk_pct=0.003,
        volume_price_risk_sizing_max_weight=0.12,
        volume_price_min_stop_distance_pct=0.015,
        volume_price_min_raw_stop_upsize_pct=0.002,
        enable_volume_price_quiet_weekly_down_exception=True,
        volume_price_quiet_weekly_down_exception_min_cases=5,
        volume_price_quiet_weekly_down_exception_min_win_rate_pct=65.0,
        volume_price_quiet_weekly_down_exception_min_avg_return_pct=0.50,
        volume_price_quiet_weekly_down_exception_max_distribution_score=65.0,
    )

    return (
        TrainingCandidate(
            name="baseline_discipline",
            skill_lenses=("current_program", "trade_journal"),
            hypothesis="Keep the current discipline as the benchmark.",
            config=DisciplineConfig(),
            tier="core",
        ),
        TrainingCandidate(
            name="smart_money_strict",
            skill_lenses=("smart_money_tracker", "a_share_flow"),
            hypothesis=(
                "Only act when main-flow evidence is stronger and distribution risk is lower."
            ),
            config=DisciplineConfig(
                breakout_weight=0.25,
                accumulation_weight=0.18,
                min_markup_score=62.0,
                min_accumulation_score=72.0,
                max_distribution_entry_score=55.0,
                exit_distribution_score=68.0,
                min_pursuit_main_pct=10.0,
                max_pursuit_distribution_score=55.0,
                min_pursuit_volume_ratio=1.8,
            ),
        ),
        TrainingCandidate(
            name="breakout_only_no_pursuit",
            skill_lenses=("event_backtest", "risk_gate"),
            hypothesis=(
                "Disable pursuit probes and only allow confirmed breakout/accumulation entries."
            ),
            config=DisciplineConfig(
                enable_pursuit_probe=False,
            ),
        ),
        TrainingCandidate(
            name="active_probe_with_inferred_exit",
            skill_lenses=("risk_reward_gate", "smart_money_tracker", "early_exit"),
            hypothesis=(
                "Increase candidate trades through risk-gated small probes, "
                "and exit early when flow pressure weakens."
            ),
            config=DisciplineConfig(
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
            ),
        ),
        TrainingCandidate(
            name="volume_price_trial_probe",
            skill_lenses=("volume_price_replay", "event_backtest", "risk_gate"),
            hypothesis=(
                "Use prior resolved same-node volume-price outcomes to permit small "
                "next-open trial buys even when fund-flow coverage is incomplete."
            ),
            config=discipline_config_for_mode("volume-probe"),
        ),
        TrainingCandidate(
            name="volume_price_intent_filtered_probe",
            skill_lenses=(
                "volume_price_replay",
                "main_force_intent",
                "risk_gate",
            ),
            hypothesis=(
                "Keep the same volume-price trial gate, but block non-breakout "
                "quiet-consolidation trial buys when the weekly trend is already "
                "down."
            ),
            config=replace(
                discipline_config_for_mode("volume-probe"),
                enable_volume_price_intent_filter=True,
                volume_price_dry_up_min_close_vs_vwap60_pct=-100.0,
                volume_price_block_non_breakout_markdown=False,
            ),
        ),
        TrainingCandidate(
            name="volume_price_risk_sized_probe",
            skill_lenses=(
                "volume_price_replay",
                "main_force_intent",
                "support_risk_budget",
            ),
            hypothesis=(
                "Use the intent-filtered volume-price trial gate, then size the "
                "next-open entry from account risk divided by the distance from "
                "actual open to signal-day low support."
            ),
            config=replace(
                discipline_config_for_mode("volume-probe"),
                enable_volume_price_intent_filter=True,
                volume_price_dry_up_min_close_vs_vwap60_pct=-100.0,
                volume_price_block_non_breakout_markdown=False,
                enable_volume_price_risk_sizing=True,
                volume_price_account_risk_pct=0.003,
                volume_price_risk_sizing_max_weight=0.12,
                volume_price_min_stop_distance_pct=0.015,
            ),
        ),
        TrainingCandidate(
            name="volume_price_markdown_guard_probe",
            skill_lenses=(
                "volume_price_replay",
                "main_force_intent",
                "markdown_phase_guard",
                "support_risk_budget",
            ),
            hypothesis=(
                "Keep risk-sized volume-price entries, but block non-breakout "
                "trial buys when the main-force intent proxy classifies the "
                "signal day as markdown risk."
            ),
            config=replace(
                discipline_config_for_mode("volume-probe"),
                enable_volume_price_intent_filter=True,
                volume_price_dry_up_min_close_vs_vwap60_pct=-100.0,
                volume_price_block_non_breakout_markdown=True,
                enable_volume_price_risk_sizing=True,
                volume_price_account_risk_pct=0.003,
                volume_price_risk_sizing_max_weight=0.12,
                volume_price_min_stop_distance_pct=0.015,
                volume_price_min_raw_stop_upsize_pct=0.002,
            ),
        ),
        TrainingCandidate(
            name="volume_price_dry_up_flow_support_guard_probe",
            skill_lenses=(
                "volume_price_replay",
                "main_force_intent",
                "dry_up_phase_flow_guard",
                "opening_support_guard",
                "support_risk_budget",
            ),
            hypothesis=(
                "Keep the markdown guard, but make it dry-up specific: block "
                "dry-up base entries in markdown/weekly-down risk, reject high "
                "distribution risk, require non-negative 10-day flow when "
                "available, and only execute near a usable support distance."
            ),
            config=replace(
                discipline_config_for_mode("volume-probe"),
                enable_volume_price_intent_filter=True,
                volume_price_dry_up_min_close_vs_vwap60_pct=-100.0,
                volume_price_block_non_breakout_markdown=False,
                enable_volume_price_dry_up_guard=True,
                volume_price_dry_up_max_distribution_score=40.0,
                volume_price_dry_up_require_nonnegative_main_flow_10=True,
                volume_price_dry_up_min_support_distance_pct=0.5,
                volume_price_dry_up_max_support_distance_pct=2.0,
                volume_price_dry_up_max_opening_gap_pct=1.0,
                enable_volume_price_risk_sizing=True,
                volume_price_account_risk_pct=0.003,
                volume_price_risk_sizing_max_weight=0.12,
                volume_price_min_stop_distance_pct=0.015,
                volume_price_min_raw_stop_upsize_pct=0.002,
            ),
        ),
        TrainingCandidate(
            name="volume_price_support_quality_probe",
            skill_lenses=(
                "volume_price_replay",
                "main_force_intent",
                "support_quality_gate",
            ),
            hypothesis=(
                "Keep risk-sized volume-price entries, but block dry-up base "
                "nodes unless fund-flow coverage and historical edge support "
                "the support-quality thesis."
            ),
            config=replace(
                discipline_config_for_mode("volume-probe"),
                enable_volume_price_intent_filter=True,
                enable_volume_price_support_quality_filter=True,
                volume_price_block_dry_up_without_main_flow=True,
                volume_price_support_quality_min_dry_up_avg_return_pct=0.35,
                volume_price_block_non_breakout_markdown=False,
                enable_volume_price_risk_sizing=True,
                volume_price_account_risk_pct=0.003,
                volume_price_risk_sizing_max_weight=0.12,
                volume_price_min_stop_distance_pct=0.015,
                volume_price_min_raw_stop_upsize_pct=0.002,
            ),
            tier="core",
        ),
        TrainingCandidate(
            name="volume_price_quiet_exception_probe",
            skill_lenses=(
                "volume_price_replay",
                "main_force_intent",
                "quiet_exception_gate",
                "support_risk_budget",
            ),
            hypothesis=(
                "Keep the v018 risk-sized support-quality volume-price gate, "
                "but allow quiet-consolidation weekly-down entries only when "
                "point-in-time same-node evidence is strong and distribution "
                "risk remains capped."
            ),
            config=quiet_exception_config,
        ),
        TrainingCandidate(
            name="volume_price_quiet_exception_flow_guard_probe",
            skill_lenses=(
                "volume_price_replay",
                "main_force_intent",
                "quiet_exception_gate",
                "flow_guard",
                "support_risk_budget",
            ),
            hypothesis=(
                "Keep the v020 quiet weekly-down exception, but require "
                "more resolved same-node cases, non-negative 10-day main-flow "
                "evidence, and a stricter distribution-risk cap before allowing "
                "the exception."
            ),
            config=replace(
                quiet_exception_config,
                enable_volume_price_quiet_weekly_down_exception_flow_guard=True,
                volume_price_quiet_weekly_down_exception_min_cases=10,
                volume_price_quiet_weekly_down_exception_min_main_flow_10=0.0,
                volume_price_quiet_weekly_down_exception_max_distribution_score=40.0,
            ),
            tier="core",
        ),
        TrainingCandidate(
            name="volume_price_breakout_follow_through_probe",
            skill_lenses=(
                "volume_price_replay",
                "effort_vs_result_breakout",
                "follow_through_exit",
                "support_risk_budget",
            ),
            hypothesis=(
                "Convert the v027 knowledge review into execution discipline: "
                "only allow volume_breakout / effort-vs-result breakout nodes, "
                "block shrink-pullback and quiet-consolidation failed clusters, "
                "exit next open after invalidation, exit if 1-3 bars do not "
                "confirm, and otherwise hold confirmed evidence to 3-5 bars."
            ),
            config=replace(
                discipline_config_for_mode("volume-probe"),
                volume_price_probe_allowed_node_types=("volume_breakout",),
                enable_volume_price_intent_filter=True,
                volume_price_block_non_breakout_markdown=True,
                enable_volume_price_risk_sizing=True,
                volume_price_account_risk_pct=0.003,
                volume_price_risk_sizing_max_weight=0.12,
                volume_price_min_stop_distance_pct=0.015,
                volume_price_min_raw_stop_upsize_pct=0.002,
                enable_volume_price_follow_through_exit=True,
                volume_price_follow_through_no_confirm_bars=3,
                volume_price_follow_through_max_hold_bars=5,
            ),
        ),
        TrainingCandidate(
            name="volume_price_breakout_opening_guard_probe",
            skill_lenses=(
                "volume_price_replay",
                "effort_vs_result_breakout",
                "breakout_opening_guard",
                "follow_through_exit",
                "support_risk_budget",
            ),
            hypothesis=(
                "Keep the breakout follow-through discipline, but test a narrow "
                "entry guard from the 601929 loss cluster: reject overheated "
                "breakout openings above +3%, and reject extremely wide support "
                "distance when the next open shows too little demand."
            ),
            config=replace(
                discipline_config_for_mode("volume-probe"),
                volume_price_probe_allowed_node_types=("volume_breakout",),
                enable_volume_price_intent_filter=True,
                volume_price_block_non_breakout_markdown=True,
                enable_volume_price_risk_sizing=True,
                volume_price_account_risk_pct=0.003,
                volume_price_risk_sizing_max_weight=0.12,
                volume_price_min_stop_distance_pct=0.015,
                volume_price_min_raw_stop_upsize_pct=0.002,
                enable_volume_price_follow_through_exit=True,
                volume_price_follow_through_no_confirm_bars=3,
                volume_price_follow_through_max_hold_bars=5,
                volume_price_breakout_max_opening_gap_pct=3.0,
                volume_price_breakout_wide_support_distance_pct=8.0,
                volume_price_breakout_min_gap_for_wide_support_pct=0.5,
            ),
        ),
        TrainingCandidate(
            name="volume_price_breakout_confirmation_entry_probe",
            skill_lenses=(
                "volume_price_replay",
                "effort_vs_result_breakout",
                "confirmation_entry",
                "breakout_opening_guard",
                "follow_through_exit",
                "support_risk_budget",
            ),
            hypothesis=(
                "Keep failed shrink/quiet/dry-up clusters closed, but stop "
                "treating every breakout signal as an immediate buy: observe "
                "volume-breakout trials for one bar, require price, volume, "
                "support, and main-flow confirmation, then enter at the next "
                "open only if post-signal follow-through proves the thesis."
            ),
            config=replace(
                discipline_config_for_mode("volume-probe"),
                volume_price_probe_allowed_node_types=("volume_breakout",),
                enable_volume_price_intent_filter=True,
                volume_price_block_non_breakout_markdown=True,
                enable_volume_price_risk_sizing=True,
                volume_price_account_risk_pct=0.003,
                volume_price_risk_sizing_max_weight=0.12,
                volume_price_min_stop_distance_pct=0.015,
                volume_price_min_raw_stop_upsize_pct=0.002,
                enable_volume_price_follow_through_exit=True,
                volume_price_follow_through_no_confirm_bars=3,
                volume_price_follow_through_max_hold_bars=5,
                volume_price_breakout_max_opening_gap_pct=3.0,
                volume_price_breakout_wide_support_distance_pct=8.0,
                volume_price_breakout_min_gap_for_wide_support_pct=0.5,
                enable_volume_price_breakout_confirmation_entry=True,
                volume_price_breakout_confirmation_bars=1,
            ),
        ),
        TrainingCandidate(
            name="volume_price_node_quality_expansion_probe",
            skill_lenses=(
                "volume_price_replay",
                "main_force_intent",
                "node_quality_gate",
                "support_risk_budget",
            ),
            hypothesis=(
                "Test whether lower same-node sample counts can add trades in "
                "shrink, quiet, and breakout nodes while keeping dry-up entries "
                "behind support-quality checks and requiring stronger non-dry-up "
                "history, flow, trend, and distribution-risk evidence."
            ),
            config=replace(
                discipline_config_for_mode("volume-probe"),
                enable_volume_price_intent_filter=True,
                enable_volume_price_support_quality_filter=True,
                enable_volume_price_node_quality_filter=True,
                volume_price_probe_min_cases=3,
                volume_price_probe_min_win_rate_pct=50.0,
                volume_price_probe_min_avg_return_pct=0.05,
                volume_price_dry_up_min_close_vs_vwap60_pct=-100.0,
                volume_price_block_non_breakout_markdown=False,
                volume_price_block_dry_up_without_main_flow=True,
                volume_price_support_quality_min_dry_up_avg_return_pct=0.35,
                volume_price_node_quality_min_avg_return_pct=0.35,
                volume_price_node_quality_min_win_rate_pct=60.0,
                volume_price_node_quality_min_main_flow_5=0.0,
                volume_price_node_quality_allowed_daily_trends=("up", "base_up"),
                volume_price_node_quality_allowed_weekly_trends=("up", "base_up"),
                volume_price_node_quality_max_distribution_score=55.0,
                enable_volume_price_risk_sizing=True,
                volume_price_account_risk_pct=0.003,
                volume_price_risk_sizing_max_weight=0.12,
                volume_price_min_stop_distance_pct=0.015,
                volume_price_min_raw_stop_upsize_pct=0.002,
            ),
        ),
        TrainingCandidate(
            name="pursuit_probe_only",
            skill_lenses=("smart_money_tracker", "tradingagents_analysis"),
            hypothesis=(
                "Treat strong capital-flow breakout as a small observation probe, not a full entry."
            ),
            config=DisciplineConfig(
                breakout_weight=0.12,
                accumulation_weight=0.10,
                pursuit_probe_weight=0.08,
                enable_pursuit_probe=True,
                min_pursuit_main_pct=9.0,
                max_pursuit_distribution_score=60.0,
                max_breakout_turnover_rate=12.0,
            ),
        ),
        TrainingCandidate(
            name="disguised_accumulation_probe",
            skill_lenses=("smart_money_tracker", "proof_probe"),
            hypothesis=(
                "Use point-in-time historical proof to test a small early probe before full confirmation."
            ),
            config=DisciplineConfig(
                breakout_weight=0.25,
                accumulation_weight=0.15,
                enable_accumulation_proof_probe=True,
                accumulation_proof_probe_weight=0.08,
                min_accumulation_proof_cases=5,
                min_accumulation_proof_rate_pct=60.0,
                enable_confirmation_add=True,
            ),
        ),
        TrainingCandidate(
            name="opportunity_cost_patient",
            skill_lenses=("opportunity_cost", "value_style_filter"),
            hypothesis=(
                "Reduce churn and position size; exit mostly on failed thesis or distribution evidence."
            ),
            config=DisciplineConfig(
                breakout_weight=0.20,
                accumulation_weight=0.15,
                stop_loss_pct=0.10,
                max_single_position_weight=0.30,
                enable_pursuit_probe=False,
                min_accumulation_score=70.0,
                min_markup_score=60.0,
                exit_distribution_score=82.0,
                max_breakout_close_vs_vwap60_pct=9.0,
            ),
        ),
    )


def evaluate_training_candidates(
    *,
    run_id: str,
    symbol: str,
    bars: list[Bar],
    fund_flows: list[FundFlowSnapshot],
    initial_cash: float,
    target_annual_return: float,
    candidates: Iterable[TrainingCandidate],
) -> list[CandidateResult]:
    """Evaluate candidate discipline configs on the same replay dataset."""

    results: list[CandidateResult] = []
    for candidate in candidates:
        replay = HistoricalReplayRunner(
            bars=bars,
            fund_flows=fund_flows,
            initial_cash=initial_cash,
            discipline=TradeDiscipline(candidate.config),
        ).run()
        round_trips, estimate = estimate_returns(replay.fills, replay.initial_cash)
        diagnostics = diagnose_replay(replay)
        target = assess_target_return(replay, target_annual_return)
        state = build_trading_state_model(replay, candidate.config)
        utilization = _capital_utilization(
            replay,
            include_missed_details=(
                candidate.name in MISSED_OPPORTUNITY_DETAIL_CANDIDATES
            ),
        )
        results.append(
            CandidateResult(
                run_id=run_id,
                candidate=candidate.name,
                symbol=symbol,
                skill_lenses=candidate.skill_lenses,
                hypothesis=candidate.hypothesis,
                bars_count=replay.bars_count,
                fund_flows_count=replay.fund_flows_count,
                missing_fund_flow_dates=len(replay.missing_fund_flow_dates),
                fills=len(replay.fills),
                closed_round_trips=estimate.closed_trades,
                sample_quality=estimate.sample_quality,
                final_value=round(replay.final_value, 2),
                total_return_pct=round(replay.total_return * 100, 4),
                max_drawdown_pct=round(replay.max_drawdown * 100, 4),
                expectancy_pct=_round_optional(estimate.expectancy_pct),
                account_expectancy_pct=_round_optional(estimate.account_expectancy_pct),
                profit_factor=_round_optional(estimate.profit_factor),
                target_conclusion=target.conclusion,
                evidence_score=_evidence_score(
                    sample_quality=estimate.sample_quality,
                    closed_trades=estimate.closed_trades,
                    expectancy_pct=estimate.expectancy_pct,
                    total_return_pct=replay.total_return * 100,
                    max_drawdown_pct=replay.max_drawdown * 100,
                    data_coverage_pct=_coverage_pct(replay.fund_flows_count, replay.bars_count),
                ),
                trading_mode=state.trading_mode,
                behavior_phase=state.behavior_action.phase,
                fund_flow_bias=state.fund_data.flow_bias,
                buy_state=state.buy_state,
                sell_state=state.sell_state,
                candidate_tier=candidate.tier,
                holding_days=int(utilization["holding_days"]),
                cash_days=int(utilization["cash_days"]),
                avg_position_pct=float(utilization["avg_position_pct"]),
                max_position_pct=float(utilization["max_position_pct"]),
                buy_signal_count=int(utilization["buy_signal_count"]),
                filtered_buy_signals=int(utilization["filtered_buy_signals"]),
                raw_filtered_observations=int(
                    utilization["raw_filtered_observations"]
                ),
                ordinary_non_signal_days=int(
                    utilization["ordinary_non_signal_days"]
                ),
                top_filter_reason=str(utilization["top_filter_reason"]),
                top_filter_count=int(utilization["top_filter_count"]),
                filter_attributions=utilization["filter_attributions"],
                missed_big_moves=int(utilization["missed_big_moves"]),
                missed_big_moves_filtered=int(utilization["missed_big_moves_filtered"]),
                missed_big_moves_ordinary_non_signal=int(
                    utilization["missed_big_moves_ordinary_non_signal"]
                ),
                missed_big_moves_unrecognized=int(
                    utilization["missed_big_moves_unrecognized"]
                ),
                top_missed_big_move_reason=str(
                    utilization["top_missed_big_move_reason"]
                ),
                missed_opportunity_attributions=(
                    utilization["missed_opportunity_attributions"]
                ),
                missed_opportunities=utilization["missed_opportunities"],
                loss_attributions=_loss_attributions(
                    symbol=symbol,
                    round_trips=round_trips,
                    decisions=replay.decisions,
                ),
                trade_stories=diagnostics.trade_stories,
                position_action_reviews=diagnostics.position_action_reviews,
                knowledge_hypothesis_reviews=diagnostics.knowledge_hypothesis_reviews,
            )
        )
    return results


def run_replay_training(
    *,
    symbols: list[str],
    days: int,
    initial_cash: float,
    target_annual_return: float,
    output_dir: Path,
    candidates: Iterable[TrainingCandidate] | None = None,
    pool_source: str = "manual",
    pool_seed: int | None = None,
    pool_eligible_symbols: int | None = None,
    progress_label: str | None = None,
    persist_progress: bool = False,
    progress_artifact_interval: int = 10,
) -> TrainingRun:
    """Fetch real A-share data, run candidate replays, and persist artifacts."""

    if not symbols:
        raise ValueError("symbols must not be empty")
    if days <= 0:
        raise ValueError("days must be positive")
    if initial_cash <= 0:
        raise ValueError("initial_cash must be positive")
    if progress_artifact_interval <= 0:
        raise ValueError("progress_artifact_interval must be positive")

    created_at = datetime.now(timezone.utc)
    run_id = created_at.strftime("%Y%m%dT%H%M%SZ")
    candidate_list = tuple(candidates or default_training_candidates())
    all_results: list[CandidateResult] = []
    errors: list[TrainingError] = []
    end = date.today()
    start = end - timedelta(days=days)
    fund_collector = EfinanceFundCollector()
    historical_fetcher = TrainingHistoricalBarFetcher()
    output_dir.mkdir(parents=True, exist_ok=True)
    jsonl_path = output_dir / f"{run_id}-training.jsonl"
    summary_path = output_dir / f"{run_id}-summary.md"
    missed_report_path = output_dir / (
        f"{run_id}-missed_breakout_opportunity_report.md"
    )

    total_symbols = len(symbols)
    try:
        for index, symbol in enumerate(symbols, start=1):
            if progress_label:
                print(
                    f"{progress_label}: symbol {index}/{total_symbols} {symbol}",
                    flush=True,
                )
            try:
                bars, fund_flows = _fetch_training_dataset(
                    symbol=symbol,
                    start=start,
                    end=end,
                    fund_collector=fund_collector,
                    historical_fetcher=historical_fetcher,
                )
                all_results.extend(
                    evaluate_training_candidates(
                        run_id=run_id,
                        symbol=symbol,
                        bars=bars,
                        fund_flows=fund_flows,
                        initial_cash=initial_cash,
                        target_annual_return=target_annual_return,
                        candidates=candidate_list,
                    )
                )
            except Exception as exc:  # noqa: BLE001 - data providers raise varied errors.
                errors.append(
                    TrainingError(
                        run_id=run_id,
                        symbol=symbol,
                        message=str(exc),
                    )
                )
            should_write_progress = (
                persist_progress
                and (
                    index == 1
                    or index == total_symbols
                    or index % progress_artifact_interval == 0
                )
            )
            if should_write_progress:
                write_training_artifacts(
                    TrainingRun(
                        run_id=run_id,
                        created_at=created_at.isoformat(),
                        symbols=tuple(symbols),
                        days=days,
                        initial_cash=initial_cash,
                        target_annual_return=target_annual_return,
                        candidates=tuple(
                            candidate.name for candidate in candidate_list
                        ),
                        results=tuple(all_results),
                        errors=tuple(errors),
                        jsonl_path=jsonl_path,
                        summary_path=summary_path,
                        pool_source=pool_source,
                        pool_seed=pool_seed,
                        pool_eligible_symbols=pool_eligible_symbols,
                        missed_report_path=missed_report_path,
                        processed_symbols=index,
                        is_partial=index < total_symbols,
                    )
                )
    finally:
        historical_fetcher.close()

    training_run = TrainingRun(
        run_id=run_id,
        created_at=created_at.isoformat(),
        symbols=tuple(symbols),
        days=days,
        initial_cash=initial_cash,
        target_annual_return=target_annual_return,
        candidates=tuple(candidate.name for candidate in candidate_list),
        results=tuple(all_results),
        errors=tuple(errors),
        jsonl_path=jsonl_path,
        summary_path=summary_path,
        pool_source=pool_source,
        pool_seed=pool_seed,
        pool_eligible_symbols=pool_eligible_symbols,
        missed_report_path=missed_report_path,
        processed_symbols=total_symbols,
        is_partial=False,
    )
    write_training_artifacts(training_run)
    return training_run


def render_training_summary(training_run: TrainingRun) -> str:
    """Render a Markdown summary for a training run."""

    lines = [
        f"# Training Run {training_run.run_id}",
        "",
        "- purpose: persistent paper-replay training and parameter comparison",
        "- boundary: simulated research only; not real-money advice or execution",
        f"- created_at: {training_run.created_at}",
        f"- symbols: {', '.join(training_run.symbols)}",
        f"- symbols_count: {len(training_run.symbols)}",
        f"- processed_symbols: {training_run.processed_symbols or len(training_run.symbols)}",
        f"- run_status: {'PARTIAL' if training_run.is_partial else 'FINAL'}",
        f"- days: {training_run.days}",
        f"- initial_cash: {training_run.initial_cash:.2f}",
        f"- target_annual_return_pct: {training_run.target_annual_return * 100:.2f}",
    ]
    if training_run.pool_source != "manual":
        lines.extend(
            [
                f"- pool_source: {training_run.pool_source}",
                f"- pool_seed: {training_run.pool_seed}",
                f"- pool_eligible_symbols: {training_run.pool_eligible_symbols}",
            ]
        )
    lines.extend(["", "## Ranked Candidate Results"])
    if not training_run.results:
        lines.append("No candidate results were produced.")
    else:
        lines.extend(
            [
                "rank | symbol | candidate | tier | lenses | score | sample | closed | return | max_dd | expectancy | target",
                "---: | --- | --- | --- | --- | ---: | --- | ---: | ---: | ---: | ---: | ---",
            ]
        )
        ranked = sorted(
            training_run.results,
            key=lambda item: item.evidence_score,
            reverse=True,
        )
        for index, item in enumerate(ranked, start=1):
            lines.append(
                " | ".join(
                    [
                        str(index),
                        item.symbol,
                        item.candidate,
                        item.candidate_tier,
                        ",".join(item.skill_lenses),
                        f"{item.evidence_score:.1f}",
                        item.sample_quality,
                        str(item.closed_round_trips),
                        _fmt_pct(item.total_return_pct),
                        _fmt_pct(item.max_drawdown_pct),
                        _fmt_optional_pct(item.expectancy_pct),
                        item.target_conclusion,
                    ]
                )
            )

        lines.extend(
            [
                "",
                "Latest behavior state by candidate:",
                "symbol | candidate | trading_mode | behavior_phase | fund_flow_bias | buy_state | sell_state",
                "--- | --- | --- | --- | --- | --- | ---",
            ]
        )
        for item in ranked:
            lines.append(
                " | ".join(
                    [
                        item.symbol,
                        item.candidate,
                        item.trading_mode,
                        item.behavior_phase,
                        item.fund_flow_bias,
                        item.buy_state,
                        item.sell_state,
                    ]
                )
            )

    lines.extend(["", "## Candidate Aggregate"])
    if not training_run.results:
        lines.append("No candidate results were produced.")
    else:
        aggregates = _aggregate_results(
            training_run.results,
            target_return_pct=training_run.target_annual_return * 100,
        )
        lines.extend(
            [
                "candidate | tier | symbols | traded_symbols | closed | avg_expectancy | avg_return | avg_max_dd | avg_score",
                "--- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---:",
            ]
        )
        for item in aggregates:
            lines.append(
                " | ".join(
                    [
                        item["candidate"],
                        item["tier"],
                        str(item["symbols"]),
                        str(item["traded_symbols"]),
                        str(item["closed"]),
                        _fmt_optional_pct(item["avg_expectancy"]),
                        _fmt_pct(item["avg_return"]),
                        _fmt_pct(item["avg_drawdown"]),
                        f"{item['avg_score']:.1f}",
                    ]
                )
            )
        lines.extend(
            [
                "",
                "## Candidate Promotion Gate",
                "candidate | tier | decision | reason",
                "--- | --- | --- | ---",
            ]
        )
        for item in aggregates:
            decision, reason = _promotion_decision(item)
            lines.append(f"{item['candidate']} | {item['tier']} | {decision} | {reason}")

        lines.extend(["", "## Trade Return Concentration"])
        concentration_groups = _aggregate_trade_concentration(training_run.results)
        if not concentration_groups:
            lines.append("No closed trade concentration captured.")
        else:
            lines.extend(
                [
                    "candidate | tier | trades | wins | losses | avg_trade | best | worst | top1_win_contribution | top2_win_contribution",
                    "--- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---:",
                ]
            )
            for item in concentration_groups:
                lines.append(
                    " | ".join(
                        [
                            str(item["candidate"]),
                            str(item["tier"]),
                            str(item["trades"]),
                            str(item["wins"]),
                            str(item["losses"]),
                            _fmt_pct(float(item["avg_trade_return_pct"])),
                            _fmt_pct(float(item["best_trade_pct"])),
                            _fmt_pct(float(item["worst_trade_pct"])),
                            _fmt_optional_pct(item["top1_win_contribution_pct"]),
                            _fmt_optional_pct(item["top2_win_contribution_pct"]),
                        ]
                    )
                )

        lines.extend(["", "## Capital Utilization"])
        lines.append(
            "Holding/cash days are symbol-days because current training replays one isolated account per symbol."
        )
        utilization_groups = _aggregate_capital_utilization(training_run.results)
        if not utilization_groups:
            lines.append("No capital utilization captured.")
        else:
            lines.extend(
                [
                    "candidate | tier | symbols | market_days | holding_days | holding_utilization | avg_holding_days_per_symbol | cash_days | avg_position | max_position | buy_signals | filtered_buy_signals | raw_filtered_observations | ordinary_non_signal_days | top_filter | top_filter_count | missed_big_moves | missed_filtered | missed_ordinary | missed_unrecognized",
                    "--- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---:",
                ]
            )
            for item in utilization_groups:
                lines.append(
                    " | ".join(
                        [
                            str(item["candidate"]),
                            str(item["tier"]),
                            str(item["symbols"]),
                            str(item["market_days"]),
                            str(item["holding_days"]),
                            _fmt_pct(float(item["holding_utilization_pct"])),
                            f"{float(item['avg_holding_days_per_symbol']):.1f}",
                            str(item["cash_days"]),
                            _fmt_pct(float(item["avg_position_pct"])),
                            _fmt_pct(float(item["max_position_pct"])),
                            str(item["buy_signal_count"]),
                            str(item["filtered_buy_signals"]),
                            str(item["raw_filtered_observations"]),
                            str(item["ordinary_non_signal_days"]),
                            _safe_table_text(item["top_filter_reason"]),
                            str(item["top_filter_count"]),
                            str(item["missed_big_moves"]),
                            str(item["missed_big_moves_filtered"]),
                            str(item["missed_big_moves_ordinary_non_signal"]),
                            str(item["missed_big_moves_unrecognized"]),
                        ]
                    )
                )

        lines.extend(["", "## Filter Attribution"])
        lines.append(
            "This section excludes ordinary non-signal days such as node_not_allowed:normal."
        )
        filter_groups = _aggregate_filter_attributions(training_run.results)
        if not filter_groups:
            lines.append("No filtered buy signals captured.")
        else:
            lines.extend(
                [
                    "candidate | tier | filter_reason | count",
                    "--- | --- | --- | ---:",
                ]
            )
            for item in filter_groups[:FILTER_ATTRIBUTION_LIMIT]:
                lines.append(
                    " | ".join(
                        [
                            str(item["candidate"]),
                            str(item["tier"]),
                            _safe_table_text(item["reason"]),
                            str(item["count"]),
                        ]
                    )
                )

        lines.extend(["", "## Missed Big Move Diagnostics"])
        lines.append(
            f"Big move = next {MISSED_BIG_MOVE_HORIZON_BARS} bars max close return >= {MISSED_BIG_MOVE_RETURN_PCT:.2f}% while flat."
        )
        if not utilization_groups:
            lines.append("No missed big move diagnostics captured.")
        else:
            lines.extend(
                [
                    "candidate | tier | missed_big_moves | filtered | ordinary_non_signal | unrecognized | top_reason",
                    "--- | --- | ---: | ---: | ---: | ---: | ---",
                ]
            )
            for item in utilization_groups:
                lines.append(
                    " | ".join(
                        [
                            str(item["candidate"]),
                            str(item["tier"]),
                            str(item["missed_big_moves"]),
                            str(item["missed_big_moves_filtered"]),
                            str(item["missed_big_moves_ordinary_non_signal"]),
                            str(item["missed_big_moves_unrecognized"]),
                            _safe_table_text(item["top_missed_big_move_reason"]),
                        ]
                    )
                )

        lines.extend(["", "## Missed Opportunity Attribution"])
        missed_attributions = _aggregate_missed_opportunity_attributions(
            training_run.results
        )
        if not missed_attributions:
            lines.append("No missed opportunity attribution captured.")
        else:
            lines.extend(
                [
                    "candidate | tier | attribution | count",
                    "--- | --- | --- | ---:",
                ]
            )
            for item in missed_attributions[:FILTER_ATTRIBUTION_LIMIT]:
                lines.append(
                    " | ".join(
                        [
                            str(item["candidate"]),
                            str(item["tier"]),
                            _safe_table_text(item["reason"]),
                            str(item["count"]),
                        ]
                    )
                )

        lines.extend(["", "## Missed Opportunity Detail"])
        lines.append(
            "Detailed rows are recorded for volume_price_breakout_opening_guard_probe "
            "only; they explain large forward moves that were not actually bought."
        )
        missed_details = _aggregate_missed_opportunities(training_run.results)
        if not missed_details:
            lines.append("No detailed missed opportunities captured.")
        else:
            lines.extend(
                [
                    "candidate | tier | symbol | signal_date | close | next_1d | next_3d | next_5d | max_forward | max_drawdown | max_date | attribution | volume_node | detail_reason",
                    "--- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | ---",
                ]
            )
            for item in missed_details[:MISSED_OPPORTUNITY_DETAIL_LIMIT]:
                lines.append(
                    " | ".join(
                        [
                            str(item["candidate"]),
                            str(item["tier"]),
                            str(item["symbol"]),
                            str(item["signal_date"]),
                            f"{float(item['close']):.2f}",
                            _fmt_optional_pct(item["next_1d_close_return_pct"]),
                            _fmt_optional_pct(item["next_3d_close_return_pct"]),
                            _fmt_optional_pct(item["next_5d_close_return_pct"]),
                            _fmt_pct(float(item["max_forward_return_pct"])),
                            _fmt_pct(float(item["max_forward_drawdown_pct"])),
                            str(item["max_forward_date"]),
                            _safe_table_text(item["attribution"]),
                            _safe_table_text(item["volume_node"]),
                            _safe_table_text(item["detail_reason"]),
                        ]
                    )
                )

        lines.extend(["", "## Candidate Tiers"])
        for tier, candidates in _candidate_tier_groups(training_run.results).items():
            lines.append(f"- {tier}: {', '.join(candidates)}")

        lines.extend(["", "## Loss Attribution Summary"])
        loss_groups = _aggregate_loss_attributions(training_run.results)
        if not loss_groups:
            lines.append("No losing closed trades captured.")
        else:
            lines.extend(
                [
                    "candidate | tier | symbol | entry_reason | volume_node | losses | avg_loss | total_pnl | worst",
                    "--- | --- | --- | --- | --- | ---: | ---: | ---: | ---:",
                ]
            )
            for item in loss_groups[:LOSS_ATTRIBUTION_LIMIT]:
                lines.append(
                    " | ".join(
                        [
                            item["candidate"],
                            item["tier"],
                            item["symbol"],
                            _safe_table_text(item["entry_reason"]),
                            item["volume_node"],
                            str(item["trades"]),
                            _fmt_pct(item["avg_loss_return_pct"]),
                            f"{item['total_pnl']:.2f}",
                            _fmt_pct(item["worst_return_pct"]),
                        ]
                    )
                )

        lines.extend(["", "## Position Action Replay"])
        action_groups = _aggregate_position_action_reviews(training_run.results)
        if not action_groups:
            lines.append("No position action reviews captured.")
        else:
            lines.extend(
                [
                    "candidate | tier | action | trades | avg_return | avg_gap | avg_support_distance",
                    "--- | --- | --- | ---: | ---: | ---: | ---:",
                ]
            )
            for item in action_groups:
                lines.append(
                    " | ".join(
                        [
                            item["candidate"],
                            item["tier"],
                            item["action"],
                            str(item["trades"]),
                            _fmt_pct(item["avg_return"]),
                            _fmt_optional_pct(item["avg_gap"]),
                            _fmt_optional_pct(item["avg_support_distance"]),
                        ]
                    )
                )

        lines.extend(["", "## Knowledge Hypothesis Diagnostics"])
        knowledge_groups = _aggregate_knowledge_hypothesis_reviews(training_run.results)
        if not knowledge_groups:
            lines.append("No knowledge hypothesis reviews captured.")
        else:
            lines.extend(
                [
                    "candidate | tier | lens | hypothesis | bucket | trades | win_rate | avg_return | confirmed | failed | status",
                    "--- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---",
                ]
            )
            for item in knowledge_groups:
                lines.append(
                    " | ".join(
                        [
                            str(item["candidate"]),
                            str(item["tier"]),
                            str(item["lens"]),
                            str(item["hypothesis"]),
                            _safe_table_text(item["bucket"]),
                            str(item["trades"]),
                            _fmt_optional_pct(item["win_rate"]),
                            _fmt_pct(float(item["avg_return"])),
                            str(item["confirmed"]),
                            str(item["failed"]),
                            str(item["status"]),
                        ]
                    )
                )

        lines.extend(["", "## Trade Thesis Stories"])
        story_rows = _trade_story_rows(training_run.results)
        if not story_rows:
            lines.append("No closed trade thesis stories captured.")
        else:
            lines.extend(
                [
                    "candidate | tier | symbol | entry | exit | thesis | vpa_archetype | stage | expected_hold | actual_hold | confirmations | warnings | invalidations | exit_reason | return | verdict | holding_evidence",
                    "--- | --- | --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | --- | ---: | --- | ---",
                ]
            )
            for item in story_rows:
                story = item["story"]
                if not isinstance(story, TradeStory):
                    continue
                lines.append(
                    " | ".join(
                        [
                            str(item["candidate"]),
                            str(item["tier"]),
                            story.symbol,
                            story.entry_date,
                            story.exit_date,
                            story.thesis.buy_type,
                            story.thesis.vpa_archetype,
                            _safe_table_text(story.thesis.stage),
                            story.thesis.expected_holding_days,
                            str(story.actual_holding_days),
                            str(story.confirmations),
                            str(story.warnings),
                            str(story.invalidations),
                            _safe_table_text(story.exit_reason),
                            _fmt_pct(story.return_pct),
                            story.verdict,
                            _safe_table_text(story.holding_evidence),
                        ]
                    )
                )

    lines.extend(
        [
            "",
            "## Candidate Hypotheses",
        ]
    )
    seen: set[str] = set()
    for item in training_run.results:
        if item.candidate in seen:
            continue
        seen.add(item.candidate)
        lines.append(f"- {item.candidate} [{item.candidate_tier}]: {item.hypothesis}")

    if training_run.errors:
        lines.extend(["", "## Errors"])
        lines.extend(f"- {error.symbol}: {error.message}" for error in training_run.errors)

    lines.extend(
        [
            "",
            "## Next Action Rule",
            f"- Do not promote any candidate below {PROMOTION_MIN_CLOSED_TRADES} closed trades and {PROMOTION_MIN_TRADED_SYMBOLS} traded symbols.",
            f"- Require positive aggregate return and average closed-trade expectancy above {PROMOTION_MIN_NET_EXPECTANCY_PCT:.2f}% after the cost/slippage buffer.",
            f"- Require holding utilization above {PROMOTION_MIN_HOLDING_UTILIZATION_PCT:.2f}% and average position above {PROMOTION_MIN_AVG_POSITION_PCT:.2f}% so a candidate proves capital is actually deployed.",
            f"- Require aggregate return to meet the configured target annual return; the default research target is {PROMOTION_DEFAULT_TARGET_RETURN_PCT:.2f}%.",
            "- Analyze losing entry reason, volume node, and symbol clusters before adding parameters.",
        ]
    )
    return "\n".join(lines)


def render_missed_breakout_opportunity_report(
    training_run: TrainingRun,
    *,
    detail_limit: int | None = None,
) -> str:
    """Render missed large-move opportunities for the active breakout strategy."""

    missed_details = _aggregate_missed_opportunities(training_run.results)
    if detail_limit is not None:
        missed_details = missed_details[:detail_limit]

    lines = [
        f"# Missed Breakout Opportunity Report {training_run.run_id}",
        "",
        "- purpose: explain large 3-5 day moves that the active strategy did not buy",
        "- boundary: diagnostics only; no strategy weights or trade rules changed",
        f"- symbols_count: {len(training_run.symbols)}",
        f"- days: {training_run.days}",
        f"- big_move_definition: next {MISSED_BIG_MOVE_HORIZON_BARS} bars max close return >= {MISSED_BIG_MOVE_RETURN_PCT:.2f}% while flat",
        "",
        "## Attribution Summary",
    ]
    attributions = _aggregate_missed_opportunity_attributions(training_run.results)
    if not attributions:
        lines.append("No missed opportunity attribution captured.")
    else:
        lines.extend(
            [
                "candidate | tier | attribution | count",
                "--- | --- | --- | ---:",
            ]
        )
        for item in attributions[:FILTER_ATTRIBUTION_LIMIT]:
            lines.append(
                " | ".join(
                    [
                        str(item["candidate"]),
                        str(item["tier"]),
                        _safe_table_text(item["reason"]),
                        str(item["count"]),
                    ]
                )
            )

    lines.extend(["", "## Missed Opportunity Detail"])
    if not missed_details:
        lines.append("No detailed missed opportunities captured.")
    else:
        lines.extend(
            [
                "symbol | signal_date | close | next_1d | next_3d | next_5d | max_gain | max_drawdown | strategy_action | blocked_reason | volume_node | probe_passed",
                "--- | --- | ---: | ---: | ---: | ---: | ---: | ---: | --- | --- | --- | ---",
            ]
        )
        for item in missed_details:
            lines.append(
                " | ".join(
                    [
                        str(item["symbol"]),
                        str(item["signal_date"]),
                        f"{float(item['close']):.2f}",
                        _fmt_optional_pct(item["next_1d_close_return_pct"]),
                        _fmt_optional_pct(item["next_3d_close_return_pct"]),
                        _fmt_optional_pct(item["next_5d_close_return_pct"]),
                        _fmt_pct(float(item["max_forward_return_pct"])),
                        _fmt_pct(float(item["max_forward_drawdown_pct"])),
                        _strategy_action_from_attribution(str(item["attribution"])),
                        _safe_table_text(item["detail_reason"]),
                        _safe_table_text(item["volume_node"]),
                        str(item["volume_probe_passed"]),
                    ]
                )
            )
    return "\n".join(lines)


def render_expansion_validation_summary(
    training_runs: tuple[TrainingRun, ...],
) -> str:
    """Render one comparison table for 50/100/300 style expansion runs."""

    lines = [
        "# Strategy Expansion Validation",
        "",
        "- strategy: volume_price_breakout_opening_guard_probe",
        "- boundary: validation only; no trading rules or weights changed",
        "",
        "pool_size | valid_symbols | errors | closed | traded_symbols | avg_expectancy | avg_return | max_dd | holding_utilization | avg_position | cash_days | missed_big_moves | top_missed_reason | top1_win_contribution | top2_win_contribution | gate",
        "---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---",
    ]
    for run in training_runs:
        aggregate = _single_aggregate(run)
        utilization = _single_utilization(run)
        concentration = _single_trade_concentration(run)
        if aggregate is None:
            lines.append(
                f"{len(run.symbols)} | 0 | {len(run.errors)} | 0 | 0 | - | - | - | - | - | - | - | - | - | - | NO_RESULTS"
            )
            continue
        decision, reason = _promotion_decision(aggregate)
        lines.append(
            " | ".join(
                [
                    str(len(run.symbols)),
                    str(aggregate["symbols"]),
                    str(len(run.errors)),
                    str(aggregate["closed"]),
                    str(aggregate["traded_symbols"]),
                    _fmt_optional_pct(aggregate["avg_expectancy"]),
                    _fmt_pct(float(aggregate["avg_return"])),
                    _fmt_pct(float(aggregate["avg_drawdown"])),
                    _fmt_pct(float(aggregate["holding_utilization_pct"])),
                    _fmt_pct(float(aggregate["avg_position_pct"])),
                    str(utilization.get("cash_days", "-") if utilization else "-"),
                    str(utilization.get("missed_big_moves", "-") if utilization else "-"),
                    _safe_table_text(
                        str(
                            utilization.get("top_missed_big_move_reason", "-")
                            if utilization
                            else "-"
                        )
                    ),
                    _fmt_optional_pct(
                        concentration.get("top1_win_contribution_pct")
                        if concentration
                        else None
                    ),
                    _fmt_optional_pct(
                        concentration.get("top2_win_contribution_pct")
                        if concentration
                        else None
                    ),
                    _safe_table_text(f"{decision}: {reason}"),
                ]
            )
        )

    lines.extend(["", "## Output Files"])
    for run in training_runs:
        missed_path = run.missed_report_path or Path("-")
        lines.extend(
            [
                f"- pool_size={len(run.symbols)} summary={run.summary_path}",
                f"- pool_size={len(run.symbols)} missed_report={missed_path}",
                f"- pool_size={len(run.symbols)} jsonl={run.jsonl_path}",
            ]
        )
    return "\n".join(lines)


def _fetch_training_dataset(
    *,
    symbol: str,
    start: date,
    end: date,
    fund_collector: EfinanceFundCollector,
    historical_fetcher: TrainingHistoricalBarFetcher,
) -> tuple[list[Bar], list[FundFlowSnapshot]]:
    bars = historical_fetcher.fetch_daily_bars(symbol, start, end)
    fund_flows = [
        item
        for item in fund_collector.fetch_history(symbol)
        if start <= item.timestamp.date() <= end
    ]
    if not fund_flows:
        raise RuntimeError(f"no historical fund-flow rows for {symbol}")
    return bars, fund_flows


def _write_jsonl(training_run: TrainingRun) -> None:
    with training_run.jsonl_path.open("w", encoding="utf-8") as handle:
        metadata = {
            "kind": "training_run",
            "run_id": training_run.run_id,
            "created_at": training_run.created_at,
            "symbols": list(training_run.symbols),
            "days": training_run.days,
            "initial_cash": training_run.initial_cash,
            "target_annual_return": training_run.target_annual_return,
            "candidates": list(training_run.candidates),
            "pool_source": training_run.pool_source,
            "pool_seed": training_run.pool_seed,
            "pool_eligible_symbols": training_run.pool_eligible_symbols,
            "processed_symbols": training_run.processed_symbols,
            "is_partial": training_run.is_partial,
            "missed_report_path": (
                str(training_run.missed_report_path)
                if training_run.missed_report_path
                else None
            ),
        }
        handle.write(json.dumps(metadata, ensure_ascii=False) + "\n")
        for result in training_run.results:
            record = {"kind": "candidate_result", **asdict(result)}
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        for error in training_run.errors:
            record = {"kind": "training_error", **asdict(error)}
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def write_training_artifacts(training_run: TrainingRun) -> None:
    """Persist JSONL, summary, and missed-opportunity artifacts."""

    _write_jsonl(training_run)
    training_run.summary_path.write_text(
        render_training_summary(training_run),
        encoding="utf-8",
    )
    if training_run.missed_report_path:
        training_run.missed_report_path.write_text(
            render_missed_breakout_opportunity_report(training_run),
            encoding="utf-8",
        )


def _aggregate_results(
    results: tuple[CandidateResult, ...],
    *,
    target_return_pct: float = PROMOTION_DEFAULT_TARGET_RETURN_PCT,
) -> list[dict[str, object]]:
    grouped: dict[str, list[CandidateResult]] = {}
    for result in results:
        grouped.setdefault(result.candidate, []).append(result)

    aggregates: list[dict[str, object]] = []
    for candidate, items in grouped.items():
        count = len(items)
        closed = sum(item.closed_round_trips for item in items)
        avg_expectancy = _weighted_expectancy(items)
        market_days = sum(item.holding_days + item.cash_days for item in items)
        holding_days = sum(item.holding_days for item in items)
        weighted_position = sum(
            item.avg_position_pct * (item.holding_days + item.cash_days)
            for item in items
        )
        aggregates.append(
            {
                "candidate": candidate,
                "tier": _candidate_tier(items),
                "symbols": count,
                "traded_symbols": len(
                    {item.symbol for item in items if item.closed_round_trips > 0}
                ),
                "closed": closed,
                "low_confidence": sum(
                    item.sample_quality == "low_confidence" for item in items
                ),
                "no_trades": sum(
                    item.sample_quality == "no_closed_trades" for item in items
                ),
                "avg_return": sum(item.total_return_pct for item in items) / count,
                "avg_drawdown": sum(item.max_drawdown_pct for item in items) / count,
                "avg_expectancy": avg_expectancy,
                "avg_score": sum(item.evidence_score for item in items) / count,
                "market_days": market_days,
                "holding_days": holding_days,
                "holding_utilization_pct": (
                    holding_days / market_days * 100 if market_days else 0.0
                ),
                "avg_position_pct": (
                    weighted_position / market_days if market_days else 0.0
                ),
                "target_return_pct": target_return_pct,
            }
        )
    return sorted(
        aggregates,
        key=lambda item: (
            item["tier"] == "core",
            item["closed"],
            item["traded_symbols"],
            item["avg_score"],
        ),
        reverse=True,
    )


def _single_aggregate(training_run: TrainingRun) -> dict[str, object] | None:
    aggregates = _aggregate_results(
        training_run.results,
        target_return_pct=training_run.target_annual_return * 100,
    )
    return aggregates[0] if aggregates else None


def _single_utilization(training_run: TrainingRun) -> dict[str, object] | None:
    groups = _aggregate_capital_utilization(training_run.results)
    return groups[0] if groups else None


def _single_trade_concentration(training_run: TrainingRun) -> dict[str, object] | None:
    groups = _aggregate_trade_concentration(training_run.results)
    return groups[0] if groups else None


def _aggregate_trade_concentration(
    results: tuple[CandidateResult, ...],
) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str], list[TradeStory]] = {}
    for result in results:
        key = (result.candidate, result.candidate_tier)
        grouped.setdefault(key, []).extend(result.trade_stories)

    items: list[dict[str, object]] = []
    for (candidate, tier), stories in grouped.items():
        if not stories:
            continue
        returns = [story.return_pct for story in stories]
        wins = sorted(
            (story.return_pct for story in stories if story.return_pct > 0),
            reverse=True,
        )
        total_win_return = sum(wins)
        top1 = wins[0] / total_win_return * 100 if total_win_return > 0 else None
        top2 = sum(wins[:2]) / total_win_return * 100 if total_win_return > 0 else None
        items.append(
            {
                "candidate": candidate,
                "tier": tier,
                "trades": len(stories),
                "wins": sum(story.return_pct > 0 for story in stories),
                "losses": sum(story.return_pct < 0 for story in stories),
                "avg_trade_return_pct": sum(returns) / len(returns),
                "best_trade_pct": max(returns),
                "worst_trade_pct": min(returns),
                "top1_win_contribution_pct": top1,
                "top2_win_contribution_pct": top2,
            }
        )
    return sorted(
        items,
        key=lambda item: (
            str(item["tier"]) == "core",
            int(item["trades"]),
            float(item["avg_trade_return_pct"]),
        ),
        reverse=True,
    )


def _aggregate_capital_utilization(
    results: tuple[CandidateResult, ...],
) -> list[dict[str, object]]:
    grouped: dict[str, list[CandidateResult]] = {}
    for result in results:
        grouped.setdefault(result.candidate, []).append(result)

    items: list[dict[str, object]] = []
    for candidate, candidate_results in grouped.items():
        symbols = len(candidate_results)
        market_days = sum(item.holding_days + item.cash_days for item in candidate_results)
        holding_days = sum(item.holding_days for item in candidate_results)
        filter_counter: Counter[str] = Counter()
        missed_counter: Counter[str] = Counter()
        for result in candidate_results:
            for attribution in result.filter_attributions:
                filter_counter[attribution.reason] += attribution.count
            for attribution in result.missed_opportunity_attributions:
                missed_counter[attribution.reason] += attribution.count
        top_filter_reason, top_filter_count = _top_counter(filter_counter)
        top_missed_reason, _ = _top_counter(missed_counter)
        weighted_position = sum(
            item.avg_position_pct * (item.holding_days + item.cash_days)
            for item in candidate_results
        )
        items.append(
            {
                "candidate": candidate,
                "tier": _candidate_tier(candidate_results),
                "symbols": symbols,
                "market_days": market_days,
                "holding_days": holding_days,
                "holding_utilization_pct": (
                    holding_days / market_days * 100 if market_days else 0.0
                ),
                "avg_holding_days_per_symbol": (
                    holding_days / symbols if symbols else 0.0
                ),
                "cash_days": sum(item.cash_days for item in candidate_results),
                "avg_position_pct": (
                    weighted_position / market_days if market_days else 0.0
                ),
                "max_position_pct": max(
                    (item.max_position_pct for item in candidate_results),
                    default=0.0,
                ),
                "buy_signal_count": sum(
                    item.buy_signal_count for item in candidate_results
                ),
                "filtered_buy_signals": sum(
                    item.filtered_buy_signals for item in candidate_results
                ),
                "raw_filtered_observations": sum(
                    item.raw_filtered_observations for item in candidate_results
                ),
                "ordinary_non_signal_days": sum(
                    item.ordinary_non_signal_days for item in candidate_results
                ),
                "top_filter_reason": top_filter_reason,
                "top_filter_count": top_filter_count,
                "missed_big_moves": sum(
                    item.missed_big_moves for item in candidate_results
                ),
                "missed_big_moves_filtered": sum(
                    item.missed_big_moves_filtered for item in candidate_results
                ),
                "missed_big_moves_ordinary_non_signal": sum(
                    item.missed_big_moves_ordinary_non_signal
                    for item in candidate_results
                ),
                "missed_big_moves_unrecognized": sum(
                    item.missed_big_moves_unrecognized for item in candidate_results
                ),
                "top_missed_big_move_reason": top_missed_reason,
            }
        )
    return sorted(
        items,
        key=lambda item: (
            str(item["tier"]) == "core",
            int(item["holding_days"]),
            int(item["buy_signal_count"]),
        ),
        reverse=True,
    )


def _aggregate_filter_attributions(
    results: tuple[CandidateResult, ...],
) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str, str], int] = {}
    for result in results:
        for attribution in result.filter_attributions:
            key = (result.candidate, result.candidate_tier, attribution.reason)
            grouped[key] = grouped.get(key, 0) + attribution.count
    return sorted(
        (
            {
                "candidate": candidate,
                "tier": tier,
                "reason": reason,
                "count": count,
            }
            for (candidate, tier, reason), count in grouped.items()
        ),
        key=lambda item: (
            str(item["candidate"]),
            -int(item["count"]),
            str(item["reason"]),
        ),
    )


def _aggregate_missed_opportunities(
    results: tuple[CandidateResult, ...],
) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    for result in results:
        for opportunity in result.missed_opportunities:
            items.append(
                {
                    "candidate": result.candidate,
                    "tier": result.candidate_tier,
                    "symbol": opportunity.symbol,
                    "signal_date": opportunity.signal_date,
                    "close": opportunity.close,
                    "next_1d_close_return_pct": (
                        opportunity.next_1d_close_return_pct
                    ),
                    "next_3d_close_return_pct": (
                        opportunity.next_3d_close_return_pct
                    ),
                    "next_5d_close_return_pct": (
                        opportunity.next_5d_close_return_pct
                    ),
                    "max_forward_return_pct": opportunity.max_forward_return_pct,
                    "max_forward_date": opportunity.max_forward_date,
                    "max_forward_drawdown_pct": (
                        opportunity.max_forward_drawdown_pct
                    ),
                    "attribution": opportunity.attribution,
                    "detail_reason": opportunity.detail_reason,
                    "volume_node": opportunity.volume_node,
                    "volume_probe_passed": opportunity.volume_probe_passed,
                }
            )
    return sorted(
        items,
        key=lambda item: (
            float(item["max_forward_return_pct"]),
            str(item["signal_date"]),
        ),
        reverse=True,
    )


def _aggregate_missed_opportunity_attributions(
    results: tuple[CandidateResult, ...],
) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str, str], int] = {}
    for result in results:
        for attribution in result.missed_opportunity_attributions:
            key = (result.candidate, result.candidate_tier, attribution.reason)
            grouped[key] = grouped.get(key, 0) + attribution.count
    return sorted(
        (
            {
                "candidate": candidate,
                "tier": tier,
                "reason": reason,
                "count": count,
            }
            for (candidate, tier, reason), count in grouped.items()
        ),
        key=lambda item: (
            str(item["candidate"]),
            -int(item["count"]),
            str(item["reason"]),
        ),
    )


def _top_counter(counter: Counter[str]) -> tuple[str, int]:
    if not counter:
        return "-", 0
    return sorted(counter.items(), key=lambda item: (-item[1], item[0]))[0]


def _promotion_decision(aggregate: dict[str, object]) -> tuple[str, str]:
    closed = int(aggregate["closed"])
    avg_return = float(aggregate["avg_return"])
    symbols = int(aggregate["symbols"])
    traded_symbols = int(aggregate.get("traded_symbols", symbols if closed > 0 else 0))
    holding_utilization_pct = float(aggregate.get("holding_utilization_pct", 0.0))
    avg_position_pct = float(aggregate.get("avg_position_pct", 0.0))
    target_return_pct = float(
        aggregate.get("target_return_pct", PROMOTION_DEFAULT_TARGET_RETURN_PCT)
    )
    avg_expectancy = aggregate.get("avg_expectancy")
    avg_expectancy_pct = (
        None if avg_expectancy is None else float(avg_expectancy)
    )
    if closed < PROMOTION_MIN_CLOSED_TRADES:
        return (
            "OBSERVE",
            f"needs at least {PROMOTION_MIN_CLOSED_TRADES} closed trades; got {closed}",
        )
    if traded_symbols < PROMOTION_MIN_TRADED_SYMBOLS:
        return (
            "OBSERVE",
            "needs multi-symbol closed-trade coverage: "
            f"{traded_symbols}/{PROMOTION_MIN_TRADED_SYMBOLS}",
        )
    if avg_expectancy_pct is None:
        return "OBSERVE", "closed-trade expectancy is not available"
    if avg_expectancy_pct <= 0:
        return (
            "OBSERVE",
            f"closed-trade expectancy must stay positive; got {avg_expectancy_pct:.2f}%",
        )
    if avg_expectancy_pct < PROMOTION_MIN_NET_EXPECTANCY_PCT:
        return (
            "OBSERVE",
            "average closed-trade return is below the cost/slippage buffer: "
            f"{avg_expectancy_pct:.2f}% < {PROMOTION_MIN_NET_EXPECTANCY_PCT:.2f}%",
        )
    if holding_utilization_pct < PROMOTION_MIN_HOLDING_UTILIZATION_PCT:
        return (
            "OBSERVE",
            "holding utilization is too low to prove deployable capital: "
            f"{holding_utilization_pct:.2f}% < "
            f"{PROMOTION_MIN_HOLDING_UTILIZATION_PCT:.2f}%",
        )
    if avg_position_pct < PROMOTION_MIN_AVG_POSITION_PCT:
        return (
            "OBSERVE",
            "average position is too low to explain annual return potential: "
            f"{avg_position_pct:.2f}% < {PROMOTION_MIN_AVG_POSITION_PCT:.2f}%",
        )
    if avg_return <= 0:
        return "OBSERVE", f"aggregate return must be positive; got {avg_return:.2f}%"
    if avg_return < target_return_pct:
        return (
            "OBSERVE",
            "aggregate return is below the configured annual target: "
            f"{avg_return:.2f}% < {target_return_pct:.2f}%",
        )
    return (
        "PROMOTE_CANDIDATE",
        "sample, expectancy, utilization, position, and target-return gates all passed",
    )


def _capital_utilization(
    replay: ReplayResult,
    *,
    include_missed_details: bool = False,
) -> dict[str, object]:
    snapshots = replay.equity_curve
    market_days = len(snapshots)
    position_pcts = [
        (snapshot.market_value / snapshot.total_value * 100)
        if snapshot.total_value > 0
        else 0.0
        for snapshot in snapshots
    ]
    holding_days = sum(snapshot.market_value > 0 for snapshot in snapshots)
    raw_filter_attributions = _filter_attributions(
        replay.decisions,
        replay.skipped_orders,
        include_ordinary=True,
    )
    filter_attributions = _filter_attributions(
        replay.decisions,
        replay.skipped_orders,
        include_ordinary=False,
    )
    top_filter = filter_attributions[0] if filter_attributions else None
    missed = _missed_big_move_stats(
        replay,
        include_details=include_missed_details,
    )
    executed_buys = sum(1 for decision in replay.decisions if decision.side == "BUY")
    return {
        "holding_days": holding_days,
        "cash_days": market_days - holding_days,
        "avg_position_pct": round(
            sum(position_pcts) / market_days if market_days else 0.0,
            4,
        ),
        "max_position_pct": round(max(position_pcts) if position_pcts else 0.0, 4),
        "buy_signal_count": executed_buys + sum(
            item.count for item in filter_attributions
        ),
        "filtered_buy_signals": sum(item.count for item in filter_attributions),
        "raw_filtered_observations": sum(item.count for item in raw_filter_attributions),
        "ordinary_non_signal_days": _ordinary_non_signal_filter_count(replay.decisions),
        "top_filter_reason": top_filter.reason if top_filter else "-",
        "top_filter_count": top_filter.count if top_filter else 0,
        "filter_attributions": filter_attributions,
        "missed_big_moves": missed["missed_big_moves"],
        "missed_big_moves_filtered": missed["missed_big_moves_filtered"],
        "missed_big_moves_ordinary_non_signal": missed[
            "missed_big_moves_ordinary_non_signal"
        ],
        "missed_big_moves_unrecognized": missed["missed_big_moves_unrecognized"],
        "top_missed_big_move_reason": missed["top_missed_big_move_reason"],
        "missed_opportunity_attributions": missed[
            "missed_opportunity_attributions"
        ],
        "missed_opportunities": missed["missed_opportunities"],
    }


def _filter_attributions(
    decisions: list[ReplayDecision],
    skipped_orders: list[str],
    *,
    include_ordinary: bool,
) -> tuple[FilterAttribution, ...]:
    counter: Counter[str] = Counter()
    for decision in decisions:
        if _is_filtered_buy_signal(decision):
            bucket = _filter_reason_bucket(decision.reason)
            if include_ordinary or not _is_ordinary_non_signal_reason(bucket):
                counter[bucket] += 1
    for skipped in skipped_orders:
        bucket = _filter_reason_bucket(skipped)
        if include_ordinary or not _is_ordinary_non_signal_reason(bucket):
            counter[bucket] += 1
    return tuple(
        FilterAttribution(reason=reason, count=count)
        for reason, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    )


def _ordinary_non_signal_filter_count(decisions: list[ReplayDecision]) -> int:
    return sum(
        1
        for decision in decisions
        if _is_filtered_buy_signal(decision)
        and _is_ordinary_non_signal_reason(_filter_reason_bucket(decision.reason))
    )


def _is_filtered_buy_signal(decision: ReplayDecision) -> bool:
    if decision.side is not None:
        return False
    reason = decision.reason
    filtered_prefixes = (
        "volume_price_trial_blocked:",
        "volume_price_opening_cancel:",
        "volume_price_breakout_confirmation_cancel:",
        "volume_price_breakout_confirmation_wait:",
    )
    if reason.startswith(filtered_prefixes):
        return True
    return (
        reason == "hold/signal entries disabled by strategy mode"
        and decision.fund_signal == "买入"
    )


def _is_ordinary_non_signal_reason(reason: str) -> bool:
    return reason == "node_not_allowed:normal"


def _filter_reason_bucket(reason: str) -> str:
    text = reason.strip()
    if ": " in text:
        text = text.split(": ", 1)[1].strip()
    if "; " in text:
        text = text.split("; ", 1)[1].strip()
    if text.startswith("original="):
        text = text.removeprefix("original=").strip()
    if " original=" in text:
        text = text.split(" original=", 1)[0].strip()
    if " expected_gap=" in text:
        text = text.split(" expected_gap=", 1)[0].strip()
    token = text.split()[0] if text.split() else reason.strip()
    if "=" in token and not token.startswith(("gap=", "support=", "elapsed=")):
        return token.split("=", 1)[0]
    return token.rstrip(";")


def _missed_big_move_stats(
    replay: ReplayResult,
    *,
    include_details: bool = False,
) -> dict[str, object]:
    missed = 0
    filtered = 0
    ordinary_non_signal = 0
    unrecognized = 0
    reasons: Counter[str] = Counter()
    details: list[MissedOpportunity] = []
    decisions_by_date: dict[date, list[ReplayDecision]] = {}
    for decision in replay.decisions:
        decisions_by_date.setdefault(decision.signal_date, []).append(decision)
    buy_fill_dates = _buy_fill_dates(replay)
    skipped_by_date = _skipped_orders_by_date(replay.skipped_orders)

    for index, bar in enumerate(replay.bars):
        if index >= len(replay.bars) - 1:
            continue
        snapshot = replay.equity_curve[index] if index < len(replay.equity_curve) else None
        if snapshot is not None and snapshot.market_value > 0:
            continue
        future_bars = replay.bars[
            index + 1:index + 1 + MISSED_BIG_MOVE_HORIZON_BARS
        ]
        if not future_bars or bar.close <= 0:
            continue
        forward_return = (max(item.close for item in future_bars) / bar.close - 1) * 100
        if forward_return < MISSED_BIG_MOVE_RETURN_PCT:
            continue

        same_day_decisions = decisions_by_date.get(bar.trade_date, [])
        next_bar = replay.bars[index + 1]
        if next_bar.trade_date in buy_fill_dates:
            continue
        missed += 1
        attribution, detail_reason, volume_decision = _missed_opportunity_attribution(
            same_day_decisions=same_day_decisions,
            skipped_next_day=skipped_by_date.get(next_bar.trade_date, ()),
        )
        if attribution in {
            "opening_guard_cancel",
            "main_flow_or_support_risk_block",
            "history_gate_failed",
            "not_volume_breakout",
            "other_filtered_signal",
        }:
            filtered += 1
        elif attribution == "ordinary_non_signal":
            ordinary_non_signal += 1
        else:
            unrecognized += 1
        reasons[attribution] += 1
        if include_details:
            max_bar = max(future_bars, key=lambda item: item.close)
            details.append(
                MissedOpportunity(
                    symbol=bar.symbol,
                    signal_date=bar.trade_date.isoformat(),
                    close=round(bar.close, 4),
                    next_1d_close_return_pct=_forward_close_return_pct(
                        bar,
                        future_bars,
                        1,
                    ),
                    next_3d_close_return_pct=_forward_close_return_pct(
                        bar,
                        future_bars,
                        3,
                    ),
                    next_5d_close_return_pct=_forward_close_return_pct(
                        bar,
                        future_bars,
                        5,
                    ),
                    max_forward_return_pct=round(forward_return, 4),
                    max_forward_date=max_bar.trade_date.isoformat(),
                    max_forward_drawdown_pct=_forward_max_drawdown_pct(
                        bar,
                        future_bars,
                    ),
                    attribution=attribution,
                    detail_reason=detail_reason,
                    volume_node=volume_decision.volume_node
                    if volume_decision and volume_decision.volume_node
                    else "-",
                    volume_probe_passed=volume_decision.volume_probe_passed
                    if volume_decision
                    else None,
                )
            )

    top_reason = "-"
    if reasons:
        top_reason = sorted(reasons.items(), key=lambda item: (-item[1], item[0]))[0][0]
    details = sorted(
        details,
        key=lambda item: (
            item.max_forward_return_pct,
            item.next_5d_close_return_pct
            if item.next_5d_close_return_pct is not None
            else -999.0,
        ),
        reverse=True,
    )[:MISSED_OPPORTUNITY_PER_RESULT_LIMIT]
    return {
        "missed_big_moves": missed,
        "missed_big_moves_filtered": filtered,
        "missed_big_moves_ordinary_non_signal": ordinary_non_signal,
        "missed_big_moves_unrecognized": unrecognized,
        "top_missed_big_move_reason": top_reason,
        "missed_opportunity_attributions": tuple(
            FilterAttribution(reason=reason, count=count)
            for reason, count in sorted(
                reasons.items(),
                key=lambda item: (-item[1], item[0]),
            )
        ),
        "missed_opportunities": tuple(details),
    }


def _buy_fill_dates(replay: ReplayResult) -> set[date]:
    dates: set[date] = set()
    for fill in replay.fills:
        side = getattr(fill.side, "value", fill.side)
        if side == "BUY":
            dates.add(fill.trade_date)
    return dates


def _skipped_orders_by_date(skipped_orders: list[str]) -> dict[date, tuple[str, ...]]:
    grouped: dict[date, list[str]] = {}
    for skipped in skipped_orders:
        if ": " not in skipped:
            continue
        raw_date, reason = skipped.split(": ", 1)
        try:
            trade_date = date.fromisoformat(raw_date)
        except ValueError:
            continue
        grouped.setdefault(trade_date, []).append(reason)
    return {key: tuple(value) for key, value in grouped.items()}


def _missed_opportunity_attribution(
    *,
    same_day_decisions: list[ReplayDecision],
    skipped_next_day: tuple[str, ...],
) -> tuple[str, str, ReplayDecision | None]:
    opening_cancel = _latest_matching_reason(
        skipped_next_day,
        "volume_price_opening_cancel:",
    )
    volume_decision = _latest_volume_price_decision(same_day_decisions)
    if opening_cancel is not None:
        return (
            "opening_guard_cancel",
            _compact_reason(opening_cancel),
            volume_decision,
        )

    filtered_decisions = [
        decision for decision in same_day_decisions if _is_filtered_buy_signal(decision)
    ]
    if filtered_decisions:
        decision = filtered_decisions[-1]
        return (
            _filtered_missed_category(decision),
            _missed_detail_reason(decision),
            decision,
        )

    if volume_decision is not None:
        if volume_decision.side == "BUY":
            skipped_order = skipped_next_day[-1] if skipped_next_day else volume_decision.reason
            return (
                "other_filtered_signal",
                _compact_reason(skipped_order),
                volume_decision,
            )
        return (
            _filtered_missed_category(volume_decision),
            _missed_detail_reason(volume_decision),
            volume_decision,
        )

    return ("no_buy_signal", "no same-day volume-price decision", None)


def _latest_matching_reason(reasons: tuple[str, ...], prefix: str) -> str | None:
    for reason in reversed(reasons):
        if reason.startswith(prefix):
            return reason
    return None


def _latest_volume_price_decision(
    decisions: list[ReplayDecision],
) -> ReplayDecision | None:
    for decision in reversed(decisions):
        if decision.observation_type == "volume_price":
            return decision
    return None


def _filtered_missed_category(decision: ReplayDecision) -> str:
    reason = decision.reason
    bucket = _filter_reason_bucket(reason)
    if decision.volume_node == "normal":
        return "ordinary_non_signal"
    if decision.volume_node and decision.volume_node != "volume_breakout":
        if _is_ordinary_non_signal_reason(bucket):
            return "ordinary_non_signal"
        return "not_volume_breakout"
    if _is_ordinary_non_signal_reason(bucket):
        return "ordinary_non_signal"
    if any(
        token in reason
        for token in (
            "main_flow",
            "support_quality",
            "support_distance",
            "invalid_risk",
            "risk_sized_weight_zero",
            "raw_stop",
            "wide_support",
        )
    ):
        return "main_flow_or_support_risk_block"
    if any(
        token in reason
        for token in (
            "insufficient_history",
            "insufficient_same_node",
            "min_cases",
            "win=",
            "avg=",
            "history_gate",
        )
    ):
        return "history_gate_failed"
    if _is_filtered_buy_signal(decision):
        return "other_filtered_signal"
    return "no_buy_signal"


def _missed_detail_reason(decision: ReplayDecision) -> str:
    parts = []
    if decision.volume_node:
        parts.append(f"node={decision.volume_node}")
    parts.append(_compact_reason(decision.reason))
    return "; ".join(parts)


def _strategy_action_from_attribution(attribution: str) -> str:
    action_by_reason = {
        "opening_guard_cancel": "blocked_next_open",
        "main_flow_or_support_risk_block": "blocked_flow_or_support_risk",
        "history_gate_failed": "blocked_history_gate",
        "not_volume_breakout": "blocked_not_volume_breakout",
        "other_filtered_signal": "blocked_other_filter",
        "ordinary_non_signal": "no_trade_normal_node",
        "no_buy_signal": "no_trade_no_signal",
    }
    return action_by_reason.get(attribution, "no_trade_unknown")


def _compact_reason(reason: str) -> str:
    text = reason.strip()
    if "; original=" in text:
        text = text.split("; original=", 1)[0]
    if " original=" in text:
        text = text.split(" original=", 1)[0]
    if len(text) > 160:
        text = text[:157].rstrip() + "..."
    return text


def _forward_close_return_pct(
    bar: Bar,
    future_bars: list[Bar],
    offset: int,
) -> float | None:
    if bar.close <= 0 or offset <= 0 or len(future_bars) < offset:
        return None
    return round((future_bars[offset - 1].close / bar.close - 1) * 100, 4)


def _forward_max_drawdown_pct(bar: Bar, future_bars: list[Bar]) -> float:
    if bar.close <= 0 or not future_bars:
        return 0.0
    min_close = min(item.close for item in future_bars)
    return round((min_close / bar.close - 1) * 100, 4)


def _loss_attributions(
    *,
    symbol: str,
    round_trips: list[RoundTrip],
    decisions: list[ReplayDecision],
) -> tuple[LossAttribution, ...]:
    grouped: dict[tuple[str, str, str], dict[str, float | int]] = {}
    for trade in round_trips:
        if trade.net_pnl >= 0:
            continue
        decision = _decision_for_trade(decisions, trade)
        volume_node = decision.volume_node if decision and decision.volume_node else "-"
        key = (trade.symbol or symbol, trade.entry_reason, volume_node)
        stats = grouped.setdefault(
            key,
            {
                "trades": 0,
                "return_sum": 0.0,
                "total_pnl": 0.0,
                "worst_return": trade.return_pct,
            },
        )
        stats["trades"] = int(stats["trades"]) + 1
        stats["return_sum"] = float(stats["return_sum"]) + trade.return_pct
        stats["total_pnl"] = float(stats["total_pnl"]) + trade.net_pnl
        stats["worst_return"] = min(float(stats["worst_return"]), trade.return_pct)

    items: list[LossAttribution] = []
    for (item_symbol, entry_reason, volume_node), stats in grouped.items():
        trades = int(stats["trades"])
        items.append(
            LossAttribution(
                symbol=item_symbol,
                entry_reason=entry_reason,
                volume_node=volume_node,
                trades=trades,
                avg_loss_return_pct=round(float(stats["return_sum"]) / trades, 4),
                total_pnl=round(float(stats["total_pnl"]), 2),
                worst_return_pct=round(float(stats["worst_return"]), 4),
            )
        )
    return tuple(sorted(items, key=lambda item: (item.total_pnl, -item.trades)))


def _decision_for_trade(
    decisions: list[ReplayDecision],
    trade: RoundTrip,
) -> ReplayDecision | None:
    matches = [
        item
        for item in decisions
        if item.side == "BUY"
        and item.signal_date < trade.entry_date
        and item.reason == trade.entry_reason
    ]
    if matches:
        return matches[-1]
    fallback = [
        item
        for item in decisions
        if item.side == "BUY" and item.signal_date < trade.entry_date
    ]
    return fallback[-1] if fallback else None


def _aggregate_loss_attributions(
    results: tuple[CandidateResult, ...],
) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str, str, str, str], dict[str, float | int]] = {}
    for result in results:
        for loss in result.loss_attributions:
            key = (
                result.candidate,
                result.candidate_tier,
                loss.symbol,
                loss.entry_reason,
                loss.volume_node,
            )
            stats = grouped.setdefault(
                key,
                {
                    "trades": 0,
                    "return_sum": 0.0,
                    "total_pnl": 0.0,
                    "worst_return": loss.worst_return_pct,
                },
            )
            stats["trades"] = int(stats["trades"]) + loss.trades
            stats["return_sum"] = (
                float(stats["return_sum"]) + loss.avg_loss_return_pct * loss.trades
            )
            stats["total_pnl"] = float(stats["total_pnl"]) + loss.total_pnl
            stats["worst_return"] = min(
                float(stats["worst_return"]),
                loss.worst_return_pct,
            )

    items: list[dict[str, object]] = []
    for (candidate, tier, symbol, entry_reason, volume_node), stats in grouped.items():
        trades = int(stats["trades"])
        items.append(
            {
                "candidate": candidate,
                "tier": tier,
                "symbol": symbol,
                "entry_reason": entry_reason,
                "volume_node": volume_node,
                "trades": trades,
                "avg_loss_return_pct": float(stats["return_sum"]) / trades,
                "total_pnl": float(stats["total_pnl"]),
                "worst_return_pct": float(stats["worst_return"]),
            }
        )
    return sorted(items, key=lambda item: (item["total_pnl"], -item["trades"]))


def _aggregate_position_action_reviews(
    results: tuple[CandidateResult, ...],
) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str, str], dict[str, float | int]] = {}
    for result in results:
        for review in result.position_action_reviews:
            key = (
                result.candidate,
                result.candidate_tier,
                review.position_action,
            )
            stats = grouped.setdefault(
                key,
                {
                    "trades": 0,
                    "return_sum": 0.0,
                    "gap_sum": 0.0,
                    "gap_count": 0,
                    "support_sum": 0.0,
                    "support_count": 0,
                },
            )
            stats["trades"] = int(stats["trades"]) + 1
            stats["return_sum"] = float(stats["return_sum"]) + review.return_pct
            if review.gap_pct is not None:
                stats["gap_sum"] = float(stats["gap_sum"]) + review.gap_pct
                stats["gap_count"] = int(stats["gap_count"]) + 1
            if review.support_distance_pct is not None:
                stats["support_sum"] = (
                    float(stats["support_sum"]) + review.support_distance_pct
                )
                stats["support_count"] = int(stats["support_count"]) + 1

    items: list[dict[str, object]] = []
    for (candidate, tier, action), stats in grouped.items():
        trades = int(stats["trades"])
        gap_count = int(stats["gap_count"])
        support_count = int(stats["support_count"])
        items.append(
            {
                "candidate": candidate,
                "tier": tier,
                "action": action,
                "trades": trades,
                "avg_return": float(stats["return_sum"]) / trades,
                "avg_gap": (
                    float(stats["gap_sum"]) / gap_count if gap_count else None
                ),
                "avg_support_distance": (
                    float(stats["support_sum"]) / support_count
                    if support_count
                    else None
                ),
            }
        )
    return sorted(
        items,
        key=lambda item: (
            str(item["candidate"]),
            str(item["tier"]),
            -int(item["trades"]),
            str(item["action"]),
        ),
    )


def _aggregate_knowledge_hypothesis_reviews(
    results: tuple[CandidateResult, ...],
) -> list[dict[str, object]]:
    grouped: dict[tuple[str, str, str, str, str], dict[str, float | int]] = {}
    for result in results:
        for review in result.knowledge_hypothesis_reviews:
            key = (
                result.candidate,
                result.candidate_tier,
                review.lens,
                review.hypothesis_id,
                review.bucket,
            )
            stats = grouped.setdefault(
                key,
                {
                    "trades": 0,
                    "wins": 0,
                    "return_sum": 0.0,
                    "confirmed": 0,
                    "failed": 0,
                },
            )
            stats["trades"] = int(stats["trades"]) + 1
            stats["wins"] = int(stats["wins"]) + (1 if review.return_pct > 0 else 0)
            stats["return_sum"] = float(stats["return_sum"]) + review.return_pct
            if review.verdict == "thesis_confirmed":
                stats["confirmed"] = int(stats["confirmed"]) + 1
            if review.verdict == "thesis_failed":
                stats["failed"] = int(stats["failed"]) + 1

    items: list[dict[str, object]] = []
    for (candidate, tier, lens, hypothesis, bucket), stats in grouped.items():
        trades = int(stats["trades"])
        confirmed = int(stats["confirmed"])
        failed = int(stats["failed"])
        avg_return = float(stats["return_sum"]) / trades
        win_rate = int(stats["wins"]) / trades * 100 if trades else None
        items.append(
            {
                "candidate": candidate,
                "tier": tier,
                "lens": lens,
                "hypothesis": hypothesis,
                "bucket": bucket,
                "trades": trades,
                "win_rate": win_rate,
                "avg_return": avg_return,
                "confirmed": confirmed,
                "failed": failed,
                "status": _knowledge_group_status(
                    trades=trades,
                    avg_return=avg_return,
                    confirmed=confirmed,
                    failed=failed,
                ),
            }
        )
    return sorted(
        items,
        key=lambda item: (
            str(item["candidate"]),
            str(item["tier"]),
            str(item["lens"]),
            -int(item["trades"]),
            float(item["avg_return"]),
        ),
    )


def _knowledge_group_status(
    *,
    trades: int,
    avg_return: float,
    confirmed: int,
    failed: int,
) -> str:
    if trades < 5:
        return "INSUFFICIENT_EVIDENCE"
    if avg_return > 0 and confirmed > failed:
        return "REVIEW_CANDIDATE"
    return "OBSERVE_ONLY"


def _trade_story_rows(
    results: tuple[CandidateResult, ...],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for result in results:
        for story in result.trade_stories:
            rows.append(
                {
                    "candidate": result.candidate,
                    "tier": result.candidate_tier,
                    "story": story,
                }
            )
    return sorted(
        rows,
        key=lambda item: (
            str(item["candidate"]),
            _story_entry_date(item["story"]),
        ),
    )


def _story_entry_date(story: object) -> str:
    return story.entry_date if isinstance(story, TradeStory) else ""


def _candidate_tier_groups(
    results: tuple[CandidateResult, ...],
) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {"core": [], "experimental": []}
    for result in results:
        candidates = groups.setdefault(result.candidate_tier, [])
        if result.candidate not in candidates:
            candidates.append(result.candidate)
    return {tier: candidates for tier, candidates in groups.items() if candidates}


def _candidate_tier(items: list[CandidateResult]) -> str:
    for item in items:
        if item.candidate_tier == "core":
            return "core"
    if items and items[0].candidate in CORE_CANDIDATE_NAMES:
        return "core"
    return items[0].candidate_tier if items else "experimental"


def _weighted_expectancy(items: list[CandidateResult]) -> float | None:
    weighted_sum = 0.0
    closed = 0
    for item in items:
        if item.expectancy_pct is None or item.closed_round_trips <= 0:
            continue
        weighted_sum += item.expectancy_pct * item.closed_round_trips
        closed += item.closed_round_trips
    return weighted_sum / closed if closed else None


def _evidence_score(
    *,
    sample_quality: str,
    closed_trades: int,
    expectancy_pct: float | None,
    total_return_pct: float,
    max_drawdown_pct: float,
    data_coverage_pct: float,
) -> float:
    if closed_trades <= 0:
        return 0.0
    if (
        closed_trades >= 5
        and expectancy_pct is not None
        and expectancy_pct <= 0
        and total_return_pct <= 0
    ):
        return 0.0

    sample_score = {
        "no_closed_trades": 0.0,
        "too_small_do_not_project": 5.0,
        "low_confidence": 25.0,
        "medium_confidence": 40.0,
        "higher_confidence": 50.0,
    }.get(sample_quality, 0.0)
    expectancy_score = _clamp((expectancy_pct or 0.0) * 6 + 20, 0, 30)
    return_score = _clamp(total_return_pct * 2 + 10, 0, 20)
    drawdown_penalty = _clamp(max_drawdown_pct * 1.5, 0, 30)
    coverage_score = _clamp(data_coverage_pct / 5, 0, 20)
    activity_score = _clamp(closed_trades, 0, 10)
    negative_expectancy_penalty = (
        _clamp(abs(expectancy_pct) * 10, 0, 30)
        if expectancy_pct is not None and expectancy_pct <= 0
        else 0
    )
    negative_return_penalty = (
        _clamp(abs(total_return_pct) * 3, 0, 20)
        if total_return_pct <= 0
        else 0
    )
    raw_score = _clamp(
        sample_score
        + expectancy_score
        + return_score
        + coverage_score
        + activity_score
        - drawdown_penalty,
        0,
        100,
    )
    raw_score = _clamp(
        raw_score - negative_expectancy_penalty - negative_return_penalty,
        0,
        100,
    )
    sample_cap = {
        "no_closed_trades": 15.0,
        "too_small_do_not_project": 40.0,
        "low_confidence": 65.0,
        "medium_confidence": 85.0,
        "higher_confidence": 100.0,
    }.get(sample_quality, 20.0)
    if closed_trades >= 5 and (
        total_return_pct <= 0 or (expectancy_pct is not None and expectancy_pct <= 0)
    ):
        sample_cap = min(sample_cap, 25.0)
    return round(min(raw_score, sample_cap), 2)


def _coverage_pct(fund_flows_count: int, bars_count: int) -> float:
    if bars_count <= 0:
        return 0.0
    return fund_flows_count / bars_count * 100


def _round_optional(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


def _fmt_pct(value: float) -> str:
    return f"{value:.2f}%"


def _fmt_optional_pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.2f}%"


def _safe_table_text(value: object) -> str:
    return str(value).replace("|", "/")
