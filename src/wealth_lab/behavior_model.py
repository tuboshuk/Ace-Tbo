"""Multi-node fund behavior and trading-state models."""

from __future__ import annotations

from dataclasses import dataclass

from wealth_lab.decision_explainer import ActionExplanation, explain_latest_action
from wealth_lab.models import FundSignal, PatternTag
from wealth_lab.performance import estimate_returns
from wealth_lab.replay import ReplayResult
from wealth_lab.trade_discipline import DisciplineConfig


@dataclass(frozen=True)
class BehaviorNode:
    """One node in the behavior and trading-state graph."""

    node_id: str
    label: str
    status: str
    score: float
    detail: str


@dataclass(frozen=True)
class FundDataModel:
    """Structured view of current and rolling fund-flow behavior."""

    symbol: str
    trade_date: str
    data_coverage_pct: float
    latest_main_flow: float
    latest_main_pct: float | None
    flow_3: float | None
    flow_5: float | None
    flow_10: float | None
    flow_bias: str
    flow_consistency_pct: float
    large_small_divergence: bool
    price_flow_divergence: bool
    data_status: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class BehaviorActionModel:
    """Current inferred behavior phase and action bias."""

    phase: str
    action_bias: str
    confidence: float
    buy_pressure_score: float
    sell_pressure_score: float
    pattern: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class TradingStateModel:
    """Multi-node buy/sell/hold/wait state for the latest replay signal."""

    symbol: str
    trade_date: str
    trading_mode: str
    buy_state: str
    sell_state: str
    risk_state: str
    summary: str
    fund_data: FundDataModel
    behavior_action: BehaviorActionModel
    nodes: tuple[BehaviorNode, ...]
    next_steps: tuple[str, ...]


def build_trading_state_model(
    result: ReplayResult,
    config: DisciplineConfig | None = None,
) -> TradingStateModel:
    """Build a latest-signal trading-state model from replay evidence."""

    if not result.signals:
        raise ValueError("result must contain at least one signal")

    discipline_config = config or DisciplineConfig()
    latest = result.signals[-1]
    action = explain_latest_action(result, discipline_config)
    fund_data = _fund_data_model(result)
    behavior_action = _behavior_action_model(result, fund_data)
    nodes = _nodes(result, fund_data, behavior_action, action)
    trading_mode = _trading_mode(action, fund_data, behavior_action, nodes)
    buy_state, sell_state, risk_state = _state_labels(action, fund_data, behavior_action)

    return TradingStateModel(
        symbol=result.symbol,
        trade_date=latest.timestamp.date().isoformat(),
        trading_mode=trading_mode,
        buy_state=buy_state,
        sell_state=sell_state,
        risk_state=risk_state,
        summary=_summary(trading_mode, fund_data, behavior_action, action),
        fund_data=fund_data,
        behavior_action=behavior_action,
        nodes=tuple(nodes),
        next_steps=_next_steps(trading_mode, nodes),
    )


def _fund_data_model(result: ReplayResult) -> FundDataModel:
    latest = result.signals[-1]
    profile = latest.intent_profile
    flow = latest.fund_flow
    quote = latest.quote
    coverage = (
        result.fund_flows_count / result.bars_count * 100
        if result.bars_count
        else 0.0
    )
    samples = [
        flow.main_net_inflow,
        *(item for item in (
            profile.main_flow_3 if profile else None,
            profile.main_flow_5 if profile else None,
            profile.main_flow_10 if profile else None,
        ) if item is not None),
    ]
    positive = sum(item > 0 for item in samples)
    negative = sum(item < 0 for item in samples)
    flow_consistency = max(positive, negative) / len(samples) * 100 if samples else 0.0
    if positive > negative:
        flow_bias = "sustained_inflow" if flow_consistency >= 75 else "mixed_inflow"
    elif negative > positive:
        flow_bias = "sustained_outflow" if flow_consistency >= 75 else "mixed_outflow"
    else:
        flow_bias = "mixed"

    data_status = "pass" if coverage >= 80 else "watch" if coverage >= 45 else "block"
    large_small_divergence = _opposite_sign(flow.main_net_inflow, flow.small_net_inflow)
    price_flow_divergence = bool(
        quote is not None
        and quote.change_pct is not None
        and (
            (quote.change_pct > 0 and flow.main_net_inflow < 0)
            or (quote.change_pct < 0 and flow.main_net_inflow > 0)
        )
    )
    reasons = [
        f"coverage={coverage:.1f}%",
        f"flow_bias={flow_bias}",
        f"flow_consistency={flow_consistency:.1f}%",
    ]
    if latest.fund_flow.main_net_inflow_pct is not None:
        reasons.append(f"latest_main_pct={latest.fund_flow.main_net_inflow_pct:.2f}%")
    if large_small_divergence:
        reasons.append("main_flow_and_small_orders_diverge")
    if price_flow_divergence:
        reasons.append("price_and_main_flow_diverge")

    return FundDataModel(
        symbol=result.symbol,
        trade_date=latest.timestamp.date().isoformat(),
        data_coverage_pct=coverage,
        latest_main_flow=flow.main_net_inflow,
        latest_main_pct=flow.main_net_inflow_pct,
        flow_3=profile.main_flow_3 if profile else None,
        flow_5=profile.main_flow_5 if profile else None,
        flow_10=profile.main_flow_10 if profile else None,
        flow_bias=flow_bias,
        flow_consistency_pct=flow_consistency,
        large_small_divergence=large_small_divergence,
        price_flow_divergence=price_flow_divergence,
        data_status=data_status,
        reasons=tuple(reasons),
    )


def _behavior_action_model(
    result: ReplayResult,
    fund_data: FundDataModel,
) -> BehaviorActionModel:
    latest = result.signals[-1]
    profile = latest.intent_profile
    tags = set(latest.pattern_tags)
    fund_signal = latest.fund_signal
    accumulation_score = profile.accumulation_score if profile else 0.0
    markup_score = profile.markup_score if profile else 0.0
    distribution_score = profile.distribution_score if profile else 0.0
    inflow_score = _flow_pressure_score(fund_data.latest_main_pct, fund_data.latest_main_flow)
    outflow_score = _flow_pressure_score(
        None if fund_data.latest_main_pct is None else -fund_data.latest_main_pct,
        -fund_data.latest_main_flow,
    )
    buy_pressure = _clamp(
        accumulation_score * 0.30
        + markup_score * 0.30
        + inflow_score * 0.30
        + (10 if PatternTag.VOLUME_BREAKOUT in tags else 0)
        + (8 if PatternTag.VCP_SETUP in tags else 0),
        0,
        100,
    )
    sell_pressure = _clamp(
        distribution_score * 0.45
        + outflow_score * 0.35
        + (15 if PatternTag.FAILED_BREAKOUT in tags else 0)
        + (12 if fund_signal in {FundSignal.SELL, FundSignal.SUSPECTED_DISTRIBUTION} else 0),
        0,
        100,
    )

    if sell_pressure >= 70 or PatternTag.FAILED_BREAKOUT in tags:
        phase = "distribution_or_failed_breakout"
        action_bias = "sell_or_avoid"
    elif markup_score >= 70 and fund_data.flow_bias in {"sustained_inflow", "mixed_inflow"}:
        phase = "markup"
        action_bias = "buy_breakout_or_hold"
    elif accumulation_score >= 65 or fund_signal == FundSignal.SUSPECTED_ACCUMULATION:
        phase = "accumulation"
        action_bias = "observe_or_probe"
    elif fund_data.flow_bias in {"sustained_outflow", "mixed_outflow"}:
        phase = "markdown_or_outflow"
        action_bias = "avoid_or_reduce"
    else:
        phase = "neutral_observation"
        action_bias = "wait"

    confidence = _clamp(
        max(buy_pressure, sell_pressure) * 0.55
        + fund_data.flow_consistency_pct * 0.25
        + (20 if fund_data.data_status == "pass" else 10 if fund_data.data_status == "watch" else 0),
        0,
        100,
    )
    reasons = [
        f"accumulation={accumulation_score:.1f}",
        f"markup={markup_score:.1f}",
        f"distribution={distribution_score:.1f}",
        f"buy_pressure={buy_pressure:.1f}",
        f"sell_pressure={sell_pressure:.1f}",
    ]
    return BehaviorActionModel(
        phase=phase,
        action_bias=action_bias,
        confidence=confidence,
        buy_pressure_score=buy_pressure,
        sell_pressure_score=sell_pressure,
        pattern=",".join(tag.value for tag in latest.pattern_tags),
        reasons=tuple(reasons),
    )


def _nodes(
    result: ReplayResult,
    fund_data: FundDataModel,
    behavior_action: BehaviorActionModel,
    action: ActionExplanation,
) -> list[BehaviorNode]:
    _, estimate = estimate_returns(result.fills, result.initial_cash)
    sell_triggered = any(check.status == "pass" for check in action.sell_checks)
    buy_ready = action.action == "BUY_NEXT_OPEN"
    return [
        BehaviorNode(
            node_id="data_model",
            label="资金数据覆盖",
            status=fund_data.data_status,
            score=_clamp(fund_data.data_coverage_pct, 0, 100),
            detail="; ".join(fund_data.reasons),
        ),
        _status_node(
            node_id="fund_direction",
            label="主力资金方向",
            score=fund_data.flow_consistency_pct,
            pass_if=fund_data.flow_bias in {"sustained_inflow", "mixed_inflow"},
            watch_if=fund_data.flow_bias == "mixed",
            detail=(
                f"bias={fund_data.flow_bias} latest_main={fund_data.latest_main_flow:.0f} "
                f"main_pct={_fmt(fund_data.latest_main_pct)}"
            ),
        ),
        _status_node(
            node_id="behavior_action",
            label="行为动作阶段",
            score=behavior_action.confidence,
            pass_if=behavior_action.phase in {"markup", "accumulation"},
            watch_if=behavior_action.phase == "neutral_observation",
            detail=(
                f"phase={behavior_action.phase} action_bias={behavior_action.action_bias} "
                f"buy_pressure={behavior_action.buy_pressure_score:.1f} "
                f"sell_pressure={behavior_action.sell_pressure_score:.1f}"
            ),
        ),
        _status_node(
            node_id="buy_path",
            label="买入路径",
            score=80.0 if buy_ready else 35.0,
            pass_if=buy_ready,
            watch_if=behavior_action.action_bias in {"observe_or_probe", "buy_breakout_or_hold"},
            detail=f"latest_action={action.action}; {action.summary}",
        ),
        _status_node(
            node_id="sell_risk",
            label="卖出风险",
            score=100.0 - behavior_action.sell_pressure_score,
            pass_if=not sell_triggered and behavior_action.sell_pressure_score < 55,
            watch_if=behavior_action.sell_pressure_score < 70,
            detail=f"sell_triggered={sell_triggered} sell_pressure={behavior_action.sell_pressure_score:.1f}",
        ),
        _status_node(
            node_id="sample_quality",
            label="训练样本质量",
            score=min(estimate.closed_trades / 30 * 100, 100),
            pass_if=estimate.closed_trades >= 30,
            watch_if=estimate.closed_trades >= 5,
            detail=(
                f"closed_round_trips={estimate.closed_trades} "
                f"sample_quality={estimate.sample_quality} "
                f"expectancy={_fmt(estimate.expectancy_pct)}%"
            ),
        ),
        _status_node(
            node_id="position_state",
            label="持仓状态",
            score=70.0 if action.position_state == "long" else 50.0,
            pass_if=action.position_state == "long" and action.action == "HOLD_WITH_STOP",
            watch_if=action.position_state == "flat",
            detail=f"position={action.position_state} action={action.action}",
        ),
    ]


def _trading_mode(
    action: ActionExplanation,
    fund_data: FundDataModel,
    behavior_action: BehaviorActionModel,
    nodes: list[BehaviorNode],
) -> str:
    node_statuses = {node.node_id: node.status for node in nodes}
    if action.action == "SELL_NEXT_OPEN":
        return "SELL_READY"
    if behavior_action.action_bias == "sell_or_avoid":
        return "WAIT_SELL_RISK"
    if action.action == "HOLD_WITH_STOP":
        return "HOLD_WITH_STOP"
    if action.action == "BUY_NEXT_OPEN":
        if (
            node_statuses.get("data_model") == "pass"
            and node_statuses.get("sample_quality") == "pass"
        ):
            return "BUY_READY"
        return "PROBE_READY"
    if behavior_action.phase == "accumulation":
        return "WATCH_ACCUMULATION"
    if fund_data.flow_bias in {"sustained_outflow", "mixed_outflow"}:
        return "WAIT_OUTFLOW"
    return "WAIT"


def _state_labels(
    action: ActionExplanation,
    fund_data: FundDataModel,
    behavior_action: BehaviorActionModel,
) -> tuple[str, str, str]:
    buy_state = (
        "ready" if action.action == "BUY_NEXT_OPEN"
        else "watch" if behavior_action.buy_pressure_score >= 55
        else "blocked"
    )
    sell_state = (
        "ready" if action.action == "SELL_NEXT_OPEN"
        else "avoid_entry" if behavior_action.action_bias == "sell_or_avoid"
        else "watch" if behavior_action.sell_pressure_score >= 55
        else "clean"
    )
    risk_state = (
        "data_blocked" if fund_data.data_status == "block"
        else "high" if sell_state == "ready"
        else "watch" if sell_state in {"avoid_entry", "watch"} or action.action == "BUY_NEXT_OPEN"
        else "normal"
    )
    return buy_state, sell_state, risk_state


def _summary(
    trading_mode: str,
    fund_data: FundDataModel,
    behavior_action: BehaviorActionModel,
    action: ActionExplanation,
) -> str:
    return (
        f"{trading_mode}: flow={fund_data.flow_bias}, "
        f"phase={behavior_action.phase}, action={action.action}, "
        f"confidence={behavior_action.confidence:.1f}"
    )


def _next_steps(trading_mode: str, nodes: list[BehaviorNode]) -> tuple[str, ...]:
    failed = [node for node in nodes if node.status == "block"]
    if trading_mode in {"SELL_READY", "WAIT_SELL_RISK"}:
        return (
            "Do not add exposure while sell risk is active.",
            "Review failed-breakout, distribution, and stop-loss nodes before the next entry.",
        )
    if trading_mode in {"BUY_READY", "PROBE_READY"}:
        return (
            "Keep execution in paper-trading mode and respect the configured target weight.",
            "Treat this as a candidate entry unless sample_quality and data_model both pass.",
        )
    if failed:
        return tuple(
            f"Repair or wait for node: {node.node_id} ({node.detail})"
            for node in failed[:3]
        )
    return (
        "Keep observing until fund direction, behavior phase, and buy path align.",
        "Do not tune thresholds from one signal alone.",
    )


def _status_node(
    node_id: str,
    label: str,
    score: float,
    pass_if: bool,
    watch_if: bool,
    detail: str,
) -> BehaviorNode:
    if pass_if:
        status = "pass"
    elif watch_if:
        status = "watch"
    else:
        status = "block"
    return BehaviorNode(
        node_id=node_id,
        label=label,
        status=status,
        score=_clamp(score, 0, 100),
        detail=detail,
    )


def _flow_pressure_score(main_pct: float | None, main_flow: float) -> float:
    pct_score = _clamp((main_pct or 0.0) * 6, 0, 60)
    amount_score = 20 if main_flow > 0 else 0
    return _clamp(pct_score + amount_score, 0, 100)


def _opposite_sign(first: float, second: float) -> bool:
    return first * second < 0


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))


def _fmt(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}"
