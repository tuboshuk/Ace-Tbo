"""Target-return knowledge graph assessment for replay results."""

from __future__ import annotations

from dataclasses import dataclass

from wealth_lab.models import FundSignal
from wealth_lab.performance import estimate_returns
from wealth_lab.replay import ReplayResult


@dataclass(frozen=True)
class KnowledgeNode:
    """One node in the trading decision graph."""

    node_id: str
    label: str
    status: str
    score: float
    detail: str


@dataclass(frozen=True)
class TargetReturnAssessment:
    """Assessment of whether a replay is on track for a target return."""

    target_annual_return_pct: float
    actual_annualized_return_pct: float
    period_years: float
    target_period_return_pct: float
    current_period_return_pct: float
    target_final_value: float
    current_final_value: float
    gap_amount: float
    gap_return_pct: float
    nodes: tuple[KnowledgeNode, ...]
    conclusion: str


def assess_target_return(
    result: ReplayResult,
    target_annual_return: float = 0.10,
) -> TargetReturnAssessment:
    """Assess replay result against a target annual return.

    Args:
        result: Historical replay result.
        target_annual_return: Target annual return as a decimal, e.g. 0.10.

    Returns:
        A node-by-node target-return assessment.
    """

    if result.initial_cash <= 0:
        raise ValueError("initial_cash must be positive")
    if target_annual_return <= -1:
        raise ValueError("target_annual_return must be greater than -100%")

    days = max((result.last_bar_date - result.first_bar_date).days, 1)
    years = days / 365.25
    current_ratio = result.final_value / result.initial_cash
    actual_annualized = (current_ratio ** (1 / years) - 1) * 100
    target_ratio = (1 + target_annual_return) ** years
    target_final = result.initial_cash * target_ratio
    target_period_return_pct = (target_ratio - 1) * 100
    current_period_return_pct = result.total_return * 100
    gap_amount = target_final - result.final_value
    nodes = _nodes(
        result=result,
        actual_annualized_pct=actual_annualized,
        target_annual_return_pct=target_annual_return * 100,
        current_period_return_pct=current_period_return_pct,
        target_period_return_pct=target_period_return_pct,
        years=years,
    )
    return TargetReturnAssessment(
        target_annual_return_pct=target_annual_return * 100,
        actual_annualized_return_pct=actual_annualized,
        period_years=years,
        target_period_return_pct=target_period_return_pct,
        current_period_return_pct=current_period_return_pct,
        target_final_value=target_final,
        current_final_value=result.final_value,
        gap_amount=gap_amount,
        gap_return_pct=target_period_return_pct - current_period_return_pct,
        nodes=tuple(nodes),
        conclusion=_conclusion(nodes, actual_annualized, target_annual_return * 100),
    )


def _nodes(
    result: ReplayResult,
    actual_annualized_pct: float,
    target_annual_return_pct: float,
    current_period_return_pct: float,
    target_period_return_pct: float,
    years: float,
) -> list[KnowledgeNode]:
    _, estimate = estimate_returns(result.fills, result.initial_cash)
    data_coverage = (
        result.fund_flows_count / result.bars_count * 100
        if result.bars_count
        else 0.0
    )
    closed_per_year = estimate.closed_trades / years if years > 0 else 0.0
    latest_signal = result.signals[-1] if result.signals else None
    latest_profile = latest_signal.intent_profile if latest_signal else None
    entry_count = sum(1 for decision in result.decisions if decision.side == "BUY")

    return [
        _status_node(
            node_id="goal_gap",
            label="年化目标差距",
            score=_score_ratio(actual_annualized_pct, target_annual_return_pct),
            pass_if=actual_annualized_pct >= target_annual_return_pct,
            watch_if=actual_annualized_pct >= target_annual_return_pct * 0.5,
            detail=(
                f"actual={actual_annualized_pct:.2f}% target="
                f"{target_annual_return_pct:.2f}% period_gap="
                f"{target_period_return_pct - current_period_return_pct:.2f}%"
            ),
        ),
        _status_node(
            node_id="data_quality",
            label="数据覆盖",
            score=data_coverage,
            pass_if=data_coverage >= 80,
            watch_if=data_coverage >= 50,
            detail=(
                f"fund_flow_rows={result.fund_flows_count} bars={result.bars_count} "
                f"coverage={data_coverage:.1f}%"
            ),
        ),
        _status_node(
            node_id="sample_size",
            label="闭合交易样本",
            score=min(estimate.closed_trades / 30 * 100, 100),
            pass_if=estimate.closed_trades >= 30,
            watch_if=estimate.closed_trades >= 5,
            detail=(
                f"closed_round_trips={estimate.closed_trades} "
                f"sample_quality={estimate.sample_quality}"
            ),
        ),
        _status_node(
            node_id="trade_frequency",
            label="交易频率",
            score=min(closed_per_year / 12 * 100, 100),
            pass_if=closed_per_year >= 12,
            watch_if=closed_per_year >= 5,
            detail=f"closed_trades_per_year={closed_per_year:.2f} entries={entry_count}",
        ),
        _expectancy_node(estimate.expectancy_pct, estimate.sample_quality),
        _status_node(
            node_id="risk_control",
            label="回撤控制",
            score=max(0.0, 100 - result.max_drawdown * 500),
            pass_if=result.max_drawdown <= 0.10,
            watch_if=result.max_drawdown <= 0.20,
            detail=f"max_drawdown={result.max_drawdown * 100:.2f}%",
        ),
        KnowledgeNode(
            node_id="concentration",
            label="单票集中度",
            status="watch",
            score=40.0,
            detail=(
                f"single_symbol={result.symbol}; 单票可以学习，但不适合单独验证"
                "年化10%目标"
            ),
        ),
        _latest_market_node(latest_signal, latest_profile),
        _status_node(
            node_id="execution",
            label="执行和规则",
            score=100.0 if not result.skipped_orders else 40.0,
            pass_if=not result.skipped_orders,
            watch_if=len(result.skipped_orders) <= 2,
            detail=(
                "no skipped orders"
                if not result.skipped_orders
                else f"skipped_orders={len(result.skipped_orders)}"
            ),
        ),
    ]


def _expectancy_node(expectancy_pct: float | None, sample_quality: str) -> KnowledgeNode:
    if expectancy_pct is None:
        return KnowledgeNode(
            node_id="expectancy",
            label="交易期望",
            status="block",
            score=0.0,
            detail="no closed trades; cannot estimate expectancy",
        )
    if sample_quality in {"no_closed_trades", "too_small_do_not_project"}:
        status = "block"
    elif expectancy_pct > 0:
        status = "pass"
    else:
        status = "block"
    return KnowledgeNode(
        node_id="expectancy",
        label="交易期望",
        status=status,
        score=max(0.0, min(100.0, 50 + expectancy_pct * 10)),
        detail=f"expectancy_per_trade={expectancy_pct:.2f}% sample={sample_quality}",
    )


def _latest_market_node(latest_signal, latest_profile) -> KnowledgeNode:
    if latest_signal is None:
        return KnowledgeNode(
            node_id="latest_market_state",
            label="最新市场状态",
            status="block",
            score=0.0,
            detail="no latest signal",
        )
    if latest_signal.fund_signal in {FundSignal.BUY, FundSignal.SUSPECTED_ACCUMULATION}:
        status = "watch"
        score = 60.0
    elif latest_signal.fund_signal == FundSignal.SELL:
        status = "block"
        score = 25.0
    else:
        status = "watch"
        score = 45.0
    profile_detail = ""
    if latest_profile is not None:
        profile_detail = (
            f" stage={latest_profile.stage} markup={latest_profile.markup_score:.1f}"
            f" distribution={latest_profile.distribution_score:.1f}"
        )
    return KnowledgeNode(
        node_id="latest_market_state",
        label="最新市场状态",
        status=status,
        score=score,
        detail=f"latest_fund_signal={latest_signal.fund_signal.value}{profile_detail}",
    )


def _status_node(
    node_id: str,
    label: str,
    score: float,
    pass_if: bool,
    watch_if: bool,
    detail: str,
) -> KnowledgeNode:
    if pass_if:
        status = "pass"
    elif watch_if:
        status = "watch"
    else:
        status = "block"
    return KnowledgeNode(
        node_id=node_id,
        label=label,
        status=status,
        score=max(0.0, min(score, 100.0)),
        detail=detail,
    )


def _score_ratio(actual: float, target: float) -> float:
    if target <= 0:
        return 100.0 if actual >= target else 0.0
    return max(0.0, min(actual / target * 100, 100.0))


def _conclusion(
    nodes: list[KnowledgeNode],
    actual_annualized_pct: float,
    target_annual_return_pct: float,
) -> str:
    blocking_ids = {node.node_id for node in nodes if node.status == "block"}
    if actual_annualized_pct >= target_annual_return_pct and not blocking_ids:
        return "on_track_for_target"
    if {"sample_size", "data_quality", "trade_frequency"} & blocking_ids:
        return "not_enough_evidence_for_capital_allocation"
    if "goal_gap" in blocking_ids:
        return "below_target_return"
    return "watch_only"
