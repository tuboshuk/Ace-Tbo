"""Explain concrete buy/sell decisions from replay signals."""

from __future__ import annotations

from dataclasses import dataclass

from wealth_lab.accumulation_proof import (
    AccumulationProofContext,
    build_point_in_time_proof_context,
    is_disguised_accumulation_candidate,
)
from wealth_lab.models import Fill, FundSignal, OrderSide, PatternTag, StockSignal
from wealth_lab.replay import ReplayResult
from wealth_lab.trade_discipline import DisciplineConfig
from wealth_lab.trade_quality import (
    EntryQuality,
    estimate_entry_quality,
    estimate_inferred_exit_pressure,
)


@dataclass(frozen=True)
class DecisionCheck:
    """One condition in the trading checklist."""

    name: str
    status: str
    detail: str


@dataclass(frozen=True)
class ActionExplanation:
    """Human-readable action plan for the latest signal."""

    action: str
    position_state: str
    summary: str
    buy_checks: tuple[DecisionCheck, ...]
    sell_checks: tuple[DecisionCheck, ...]
    next_steps: tuple[str, ...]


@dataclass(frozen=True)
class OpportunityExplanation:
    """One observed opportunity and its trade risk gate status."""

    trade_date: str
    close: float | None
    fund_signal: str
    tags: str
    status: str
    failed_gates: tuple[str, ...]
    main_flow: float
    main_pct: float | None


def explain_entry_opportunities(
    result: ReplayResult,
    config: DisciplineConfig | None = None,
) -> tuple[OpportunityExplanation, ...]:
    """Return all entry-like observations without hiding risk-gated signals."""

    discipline_config = config or DisciplineConfig()
    opportunities: list[OpportunityExplanation] = []
    for index, signal in enumerate(result.signals):
        if not _is_entry_like_observation(signal):
            continue
        proof_context = build_point_in_time_proof_context(
            signals=result.signals,
            index=index,
            horizon=discipline_config.accumulation_proof_horizon,
            min_cases=discipline_config.min_accumulation_proof_cases,
            min_confirmation_rate_pct=discipline_config.min_accumulation_proof_rate_pct,
        )
        checks = tuple(_buy_checks(signal, discipline_config, proof_context))
        status = _opportunity_status(checks)
        opportunities.append(
            OpportunityExplanation(
                trade_date=signal.timestamp.date().isoformat(),
                close=signal.quote.price if signal.quote else None,
                fund_signal=signal.fund_signal.value,
                tags=_tags(signal),
                status=status,
                failed_gates=tuple(
                    check.name for check in _relevant_failed_buy_checks(signal, checks)
                ),
                main_flow=signal.fund_flow.main_net_inflow,
                main_pct=signal.fund_flow.main_net_inflow_pct,
            )
        )
    return tuple(opportunities)


def explain_latest_action(
    result: ReplayResult,
    config: DisciplineConfig | None = None,
) -> ActionExplanation:
    """Explain the current action plan for the latest replay signal."""

    if not result.signals:
        return ActionExplanation(
            action="NO_DATA",
            position_state="unknown",
            summary="No signal is available.",
            buy_checks=(),
            sell_checks=(),
            next_steps=("Collect quote and fund-flow data first.",),
        )

    discipline_config = config or DisciplineConfig()
    latest = result.signals[-1]
    final_positions = result.equity_curve[-1].positions if result.equity_curve else {}
    has_position = final_positions.get(result.symbol, 0) > 0
    avg_cost = _open_position_avg_cost(result.fills, result.symbol)
    proof_context = build_point_in_time_proof_context(
        signals=result.signals,
        index=len(result.signals) - 1,
        horizon=discipline_config.accumulation_proof_horizon,
        min_cases=discipline_config.min_accumulation_proof_cases,
        min_confirmation_rate_pct=discipline_config.min_accumulation_proof_rate_pct,
    )
    buy_checks = tuple(_buy_checks(latest, discipline_config, proof_context))
    sell_checks = tuple(_sell_checks(latest, discipline_config, avg_cost))

    if has_position:
        if any(check.status == "pass" for check in sell_checks):
            return ActionExplanation(
                action="SELL_NEXT_OPEN",
                position_state="long",
                summary="已有持仓，出现卖出/风控触发，下一交易日开盘模拟卖出。",
                buy_checks=buy_checks,
                sell_checks=sell_checks,
                next_steps=(
                    "Do not add to the position.",
                    "Exit first, then wait for a new setup after the failed signal clears.",
                ),
            )
        return ActionExplanation(
            action="HOLD_WITH_STOP",
            position_state="long",
            summary="已有持仓，但当前没有卖出触发，继续持有并盯止损和资金流。",
            buy_checks=buy_checks,
            sell_checks=sell_checks,
            next_steps=(
                "Keep the position only while stop-loss and distribution checks stay clean.",
                "Sell if failed breakout, sell fund signal, or distribution risk appears.",
            ),
        )

    buy_ready = _all_required_pass(buy_checks, prefix="breakout") or _all_required_pass(
        buy_checks,
        prefix="accumulation",
    ) or _all_required_pass(
        buy_checks,
        prefix="pursuit",
    ) or _all_required_pass(
        buy_checks,
        prefix="active_probe",
    ) or _all_required_pass(
        buy_checks,
        prefix="proof_probe",
    )
    if buy_ready:
        return ActionExplanation(
            action="BUY_NEXT_OPEN",
            position_state="flat",
            summary="空仓，买入路径通过，下一交易日开盘按目标仓位模拟买入。",
            buy_checks=buy_checks,
            sell_checks=sell_checks,
            next_steps=(
                "Use the configured target weight only; do not exceed max position weight.",
                "After entry, failed breakout or sell fund signal becomes the exit trigger.",
            ),
        )

    return ActionExplanation(
        action="WAIT",
        position_state="flat",
        summary="空仓等待；当前没有完整买入路径，不追单。",
        buy_checks=buy_checks,
        sell_checks=sell_checks,
        next_steps=(
            "Wait for either a confirmed breakout buy path or an accumulation buy path.",
            "If the latest signal is sell/failed breakout, keep observing instead of buying.",
        ),
    )


def _buy_checks(
    signal: StockSignal,
    config: DisciplineConfig,
    proof_context: AccumulationProofContext | None = None,
) -> list[DecisionCheck]:
    profile = signal.intent_profile
    quote = signal.quote
    flow = signal.fund_flow
    tags = set(signal.pattern_tags)
    disguised_candidate = is_disguised_accumulation_candidate(signal)
    quality = estimate_entry_quality(signal, config.min_entry_reward_risk)

    proof_probe_checks = [
        _check(
            "proof_probe_candidate",
            disguised_candidate,
            f"disguised_candidate={disguised_candidate}",
        ),
        _check(
            "proof_probe_enabled",
            config.enable_accumulation_proof_probe,
            f"enable_accumulation_proof_probe={config.enable_accumulation_proof_probe}",
        ),
        _check(
            "proof_probe_resolved_cases",
            proof_context is not None
            and proof_context.resolved >= config.min_accumulation_proof_cases,
            (
                f"resolved_cases={proof_context.resolved if proof_context else 0}; "
                f"min={config.min_accumulation_proof_cases}"
            ),
        ),
        _check(
            "proof_probe_confirmation_rate",
            proof_context is not None
            and proof_context.confirmation_rate_pct is not None
            and proof_context.confirmation_rate_pct >= config.min_accumulation_proof_rate_pct,
            (
                "confirmation_rate="
                f"{_fmt(proof_context.confirmation_rate_pct if proof_context else None)}%; "
                f"min={config.min_accumulation_proof_rate_pct:.2f}%"
            ),
        )
    ]
    breakout_checks = [
        _check(
            "breakout_fund_signal",
            signal.fund_signal == FundSignal.BUY,
            f"fund_signal={signal.fund_signal.value}; need 买入",
        ),
        _check(
            "breakout_pattern",
            PatternTag.VOLUME_BREAKOUT in tags,
            f"tags={_tags(signal)}; need 放量突破",
        ),
        _check(
            "breakout_markup_score",
            profile is not None and profile.markup_score >= config.min_markup_score,
            _profile_detail(profile, "markup", config.min_markup_score),
        ),
        _check(
            "breakout_distribution_risk",
            profile is not None
            and profile.distribution_score <= config.max_distribution_entry_score,
            _profile_detail(profile, "distribution", config.max_distribution_entry_score),
        ),
        _check(
            "breakout_not_too_far_from_vwap60",
            profile is not None
            and (
                profile.close_vs_vwap_60_pct is None
                or profile.close_vs_vwap_60_pct <= config.max_breakout_close_vs_vwap60_pct
            ),
            (
                "close_vs_vwap60="
                f"{_fmt(profile.close_vs_vwap_60_pct if profile else None)}%; "
                f"max={config.max_breakout_close_vs_vwap60_pct:.2f}%"
            ),
        ),
        _check(
            "breakout_turnover_not_overheated",
            flow.turnover_rate is None
            or flow.turnover_rate <= config.max_breakout_turnover_rate,
            (
                f"turnover={_fmt(flow.turnover_rate)}%; "
                f"max={config.max_breakout_turnover_rate:.2f}%"
            ),
        ),
        _check(
            "breakout_weekly_confirmation",
            not (
                quote is not None
                and quote.volume_ratio is not None
                and quote.volume_ratio >= 2.5
                and profile is not None
                and profile.weekly_trend != "up"
            ),
            (
                f"volume_ratio={_fmt(quote.volume_ratio if quote else None)}; "
                f"weekly={profile.weekly_trend if profile else '-'}; "
                "if volume_ratio>=2.5 then weekly must be up"
            ),
        ),
        _check(
            "breakout_no_failed_or_distribution_tag",
            PatternTag.FAILED_BREAKOUT not in tags
            and PatternTag.SUSPECTED_DISTRIBUTION not in tags,
            f"tags={_tags(signal)}; need no 突破失败/疑似派发",
        ),
        _check(
            "breakout_entry_quality",
            quality.passed,
            _quality_detail(quality, config.min_entry_reward_risk),
        ),
    ]
    accumulation_tags = {
        PatternTag.SUSPECTED_ACCUMULATION,
        PatternTag.VCP_SETUP,
    }
    accumulation_checks = [
        _check(
            "accumulation_fund_signal",
            signal.fund_signal == FundSignal.SUSPECTED_ACCUMULATION,
            f"fund_signal={signal.fund_signal.value}; need 疑似吸筹",
        ),
        _check(
            "accumulation_pattern",
            bool(accumulation_tags & tags),
            f"tags={_tags(signal)}; need 疑似吸筹 or VCP蓄势",
        ),
        _check(
            "accumulation_score",
            profile is not None
            and profile.accumulation_score >= config.min_accumulation_score,
            _profile_detail(profile, "accumulation", config.min_accumulation_score),
        ),
        _check(
            "accumulation_distribution_risk",
            profile is not None
            and profile.distribution_score <= config.max_distribution_entry_score,
            _profile_detail(profile, "distribution", config.max_distribution_entry_score),
        ),
        _check(
            "accumulation_entry_quality",
            quality.passed,
            _quality_detail(quality, config.min_entry_reward_risk),
        ),
    ]
    pursuit_checks = [
        _check(
            "pursuit_enabled",
            config.enable_pursuit_probe,
            f"enable_pursuit_probe={config.enable_pursuit_probe}",
        ),
        _check(
            "pursuit_fund_signal",
            signal.fund_signal == FundSignal.BUY,
            f"fund_signal={signal.fund_signal.value}; need 买入",
        ),
        _check(
            "pursuit_main_pct",
            flow.main_net_inflow_pct is not None
            and flow.main_net_inflow_pct >= config.min_pursuit_main_pct,
            (
                f"main_pct={_fmt(flow.main_net_inflow_pct)}%; "
                f"min={config.min_pursuit_main_pct:.2f}%"
            ),
        ),
        _check(
            "pursuit_super_large_positive",
            flow.super_large_net_inflow > 0,
            f"super_large_net_inflow={flow.super_large_net_inflow:.0f}; need > 0",
        ),
        _check(
            "pursuit_price_positive",
            quote is None
            or quote.change_pct is None
            or quote.change_pct > 0,
            f"change_pct={_fmt(quote.change_pct if quote else None)}%; need > 0",
        ),
        _check(
            "pursuit_distribution_risk",
            profile is None
            or profile.distribution_score <= config.max_pursuit_distribution_score,
            (
                "distribution_score="
                f"{_fmt(profile.distribution_score if profile else None)}; "
                f"max={config.max_pursuit_distribution_score:.2f}"
            ),
        ),
        _check(
            "pursuit_breakout_or_volume",
            PatternTag.VOLUME_BREAKOUT in tags
            or quote is None
            or quote.volume_ratio is None
            or quote.volume_ratio >= config.min_pursuit_volume_ratio,
            (
                f"tags={_tags(signal)}; volume_ratio="
                f"{_fmt(quote.volume_ratio if quote else None)}; "
                f"need breakout or volume_ratio>={config.min_pursuit_volume_ratio:.2f}"
            ),
        ),
        _check(
            "pursuit_no_failed_or_distribution_tag",
            PatternTag.FAILED_BREAKOUT not in tags
            and PatternTag.SUSPECTED_DISTRIBUTION not in tags,
            f"tags={_tags(signal)}; need no 突破失败/疑似派发",
        ),
        _check(
            "pursuit_entry_quality",
            quality.passed,
            _quality_detail(quality, config.min_entry_reward_risk),
        ),
    ]
    active_probe_tags = {
        PatternTag.VOLUME_BREAKOUT,
        PatternTag.VCP_SETUP,
        PatternTag.SUSPECTED_ACCUMULATION,
    }
    active_probe_checks = [
        _check(
            "active_probe_enabled",
            config.enable_active_probe,
            f"enable_active_probe={config.enable_active_probe}",
        ),
        _check(
            "active_probe_signal",
            signal.fund_signal in {FundSignal.BUY, FundSignal.SUSPECTED_ACCUMULATION},
            f"fund_signal={signal.fund_signal.value}; need buy or suspected_accumulation",
        ),
        _check(
            "active_probe_flow_strength",
            flow.main_net_inflow > 0
            and flow.main_net_inflow_pct is not None
            and flow.main_net_inflow_pct >= config.min_pursuit_main_pct,
            (
                f"main_flow={flow.main_net_inflow:.0f}; "
                f"main_pct={_fmt(flow.main_net_inflow_pct)}%; "
                f"min={config.min_pursuit_main_pct:.2f}%"
            ),
        ),
        _check(
            "active_probe_super_large_not_negative",
            flow.super_large_net_inflow >= 0,
            f"super_large_net_inflow={flow.super_large_net_inflow:.0f}; need >= 0",
        ),
        _check(
            "active_probe_price_not_weak",
            quote is None or quote.change_pct is None or quote.change_pct >= -2.0,
            f"change_pct={_fmt(quote.change_pct if quote else None)}%; need >= -2.00%",
        ),
        _check(
            "active_probe_distribution_risk",
            profile is None
            or profile.distribution_score <= config.max_pursuit_distribution_score,
            (
                "distribution_score="
                f"{_fmt(profile.distribution_score if profile else None)}; "
                f"max={config.max_pursuit_distribution_score:.2f}"
            ),
        ),
        _check(
            "active_probe_setup",
            bool(active_probe_tags & tags),
            f"tags={_tags(signal)}; need breakout, VCP, or suspected_accumulation",
        ),
        _check(
            "active_probe_no_failed_or_distribution_tag",
            PatternTag.FAILED_BREAKOUT not in tags
            and PatternTag.SUSPECTED_DISTRIBUTION not in tags,
            f"tags={_tags(signal)}; need no failed/distribution tag",
        ),
        _check(
            "active_probe_entry_quality",
            quality.known and quality.passed,
            _quality_detail(quality, config.min_entry_reward_risk),
        ),
    ]
    return (
        proof_probe_checks
        + breakout_checks
        + accumulation_checks
        + pursuit_checks
        + active_probe_checks
    )


def _sell_checks(
    signal: StockSignal,
    config: DisciplineConfig,
    avg_cost: float | None,
) -> list[DecisionCheck]:
    profile = signal.intent_profile
    quote = signal.quote
    stop_price = avg_cost * (1 - config.stop_loss_pct) if avg_cost else None
    pressure = estimate_inferred_exit_pressure(signal, avg_cost)
    stop_hit = (
        quote is not None
        and stop_price is not None
        and quote.price <= stop_price
    )
    return [
        _check(
            "sell_fund_signal",
            signal.fund_signal in {FundSignal.SELL, FundSignal.SUSPECTED_DISTRIBUTION},
            f"fund_signal={signal.fund_signal.value}; sell on 卖出 or 疑似出货",
        ),
        _check(
            "sell_failed_breakout",
            PatternTag.FAILED_BREAKOUT in signal.pattern_tags,
            f"tags={_tags(signal)}; sell on 突破失败",
        ),
        _check(
            "sell_distribution_pattern",
            PatternTag.SUSPECTED_DISTRIBUTION in signal.pattern_tags,
            f"tags={_tags(signal)}; sell on 疑似派发",
        ),
        _check(
            "sell_distribution_score",
            profile is not None
            and profile.distribution_score >= config.exit_distribution_score,
            (
                "distribution_score="
                f"{_fmt(profile.distribution_score if profile else None)}; "
                f"trigger={config.exit_distribution_score:.2f}"
            ),
        ),
        _check(
            "sell_stop_loss",
            stop_hit,
            (
                f"close={_fmt(quote.price if quote else None)} "
                f"avg_cost={_fmt(avg_cost)} stop={_fmt(stop_price)}"
            ),
        ),
        _check(
            "sell_inferred_exit_pressure",
            config.enable_inferred_exit and pressure.triggered,
            (
                f"enabled={config.enable_inferred_exit}; "
                f"score={pressure.score:.1f}; "
                f"reasons={','.join(pressure.reasons)}"
            ),
        ),
    ]


def _all_required_pass(checks: tuple[DecisionCheck, ...], prefix: str) -> bool:
    selected = [check for check in checks if check.name.startswith(prefix)]
    return bool(selected) and all(check.status == "pass" for check in selected)


def _is_entry_like_observation(signal: StockSignal) -> bool:
    tags = set(signal.pattern_tags)
    return (
        signal.fund_signal in {FundSignal.BUY, FundSignal.SUSPECTED_ACCUMULATION}
        or PatternTag.VOLUME_BREAKOUT in tags
        or PatternTag.SUSPECTED_ACCUMULATION in tags
        or PatternTag.VCP_SETUP in tags
        or is_disguised_accumulation_candidate(signal)
    )


def _opportunity_status(checks: tuple[DecisionCheck, ...]) -> str:
    if _all_required_pass(checks, "breakout"):
        return "TRADE_READY_BREAKOUT"
    if _all_required_pass(checks, "accumulation"):
        return "TRADE_READY_ACCUMULATION"
    if _all_required_pass(checks, "pursuit"):
        return "TRADE_READY_PURSUIT"
    if _all_required_pass(checks, "active_probe"):
        return "TRADE_READY_ACTIVE_PROBE"
    if _all_required_pass(checks, "proof_probe"):
        return "TRADE_READY_PROOF_PROBE"
    return "OBSERVE_RISK_GATED"


def _relevant_failed_buy_checks(
    signal: StockSignal,
    checks: tuple[DecisionCheck, ...],
) -> list[DecisionCheck]:
    tags = set(signal.pattern_tags)
    if is_disguised_accumulation_candidate(signal):
        prefix = "proof_probe"
    elif _active_probe_enabled(checks) and _active_probe_observation(signal):
        if _all_required_pass(checks, "active_probe"):
            return []
        prefix = "active_probe"
    elif signal.fund_signal == FundSignal.BUY or PatternTag.VOLUME_BREAKOUT in tags:
        if _all_required_pass(checks, "pursuit"):
            return []
        prefix = "breakout"
    elif (
        signal.fund_signal == FundSignal.SUSPECTED_ACCUMULATION
        or PatternTag.SUSPECTED_ACCUMULATION in tags
        or PatternTag.VCP_SETUP in tags
    ):
        prefix = "accumulation"
    else:
        prefix = ""
    return [
        check for check in checks
        if check.status == "fail" and check.name.startswith(prefix)
    ]


def _active_probe_enabled(checks: tuple[DecisionCheck, ...]) -> bool:
    return any(
        check.name == "active_probe_enabled" and check.status == "pass"
        for check in checks
    )


def _active_probe_observation(signal: StockSignal) -> bool:
    tags = set(signal.pattern_tags)
    return (
        signal.fund_signal in {FundSignal.BUY, FundSignal.SUSPECTED_ACCUMULATION}
        or PatternTag.VOLUME_BREAKOUT in tags
        or PatternTag.VCP_SETUP in tags
        or PatternTag.SUSPECTED_ACCUMULATION in tags
    )


def _check(name: str, passed: bool, detail: str) -> DecisionCheck:
    return DecisionCheck(
        name=name,
        status="pass" if passed else "fail",
        detail=detail,
    )


def _profile_detail(profile, field_name: str, threshold: float) -> str:
    if profile is None:
        return f"{field_name}=missing; threshold={threshold:.2f}"
    value = getattr(profile, f"{field_name}_score")
    return f"{field_name}_score={value:.2f}; threshold={threshold:.2f}"


def _quality_detail(quality: EntryQuality, min_reward_risk: float) -> str:
    return (
        f"known={quality.known}; passed={quality.passed}; "
        f"reward_risk={_fmt(quality.reward_risk)}; "
        f"min={min_reward_risk:.2f}; "
        f"risk_pct={_fmt(quality.risk_pct)}%; "
        f"reward_pct={_fmt(quality.reward_pct)}%; "
        f"support={_fmt(quality.support)}; target={_fmt(quality.target)}; "
        f"reason={quality.reason}"
    )


def _tags(signal: StockSignal) -> str:
    return ",".join(tag.value for tag in signal.pattern_tags)


def _fmt(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}"


def _open_position_avg_cost(fills: list[Fill], symbol: str) -> float | None:
    lots: list[tuple[int, float]] = []
    for fill in fills:
        if fill.symbol != symbol:
            continue
        if fill.side == OrderSide.BUY:
            lots.append((fill.quantity, fill.price))
            continue
        remaining = fill.quantity
        while remaining > 0 and lots:
            quantity, price = lots[0]
            matched = min(quantity, remaining)
            quantity -= matched
            remaining -= matched
            if quantity == 0:
                lots.pop(0)
            else:
                lots[0] = (quantity, price)
    total_quantity = sum(quantity for quantity, _ in lots)
    if total_quantity <= 0:
        return None
    total_cost = sum(quantity * price for quantity, price in lots)
    return total_cost / total_quantity
