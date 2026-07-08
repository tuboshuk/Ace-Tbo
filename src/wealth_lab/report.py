"""Human-readable reports for monitor replay results."""

from __future__ import annotations

from collections import Counter

from wealth_lab.accumulation_proof import build_accumulation_proof_report
from wealth_lab.behavior_model import build_trading_state_model
from wealth_lab.decision_explainer import (
    explain_entry_opportunities,
    explain_latest_action,
)
from wealth_lab.diagnostics import diagnose_replay
from wealth_lab.models import StockSignal
from wealth_lab.performance import estimate_returns
from wealth_lab.replay import ReplayResult
from wealth_lab.target_graph import assess_target_return
from wealth_lab.trade_discipline import DisciplineConfig
from wealth_lab.volume_replay import build_volume_price_replay


def render_replay_report(
    result: ReplayResult,
    recent_limit: int = 12,
    target_annual_return: float = 0.10,
    current_signal: StockSignal | None = None,
    discipline_config: DisciplineConfig | None = None,
) -> str:
    """Render a historical replay report."""

    lines = [
        f"# {result.name} {result.symbol} replay report",
        "",
        "## Data",
        f"- bars: {result.bars_count}",
        f"- fund_flow_rows: {result.fund_flows_count}",
        f"- range: {result.first_bar_date} to {result.last_bar_date}",
        f"- missing_fund_flow_dates: {len(result.missing_fund_flow_dates)}",
        "",
        "## Paper Account",
        f"- initial_cash: {result.initial_cash:.2f}",
        f"- final_value: {result.final_value:.2f}",
        f"- total_return_pct: {result.total_return * 100:.2f}",
        f"- max_drawdown_pct: {result.max_drawdown * 100:.2f}",
        f"- fills: {len(result.fills)}",
        "",
    ]
    lines.extend(_return_estimate(result))
    lines.append("")
    lines.extend(_strategy_diagnostics(result))
    lines.append("")
    lines.extend(_volume_price_replay(result))
    lines.append("")
    lines.extend(_volume_price_trial_proof(result))
    lines.append("")
    lines.extend(_target_graph(result, target_annual_return))
    lines.append("")
    lines.extend(_signal_distribution(result))
    lines.append("")
    lines.extend(_recent_signals(result, recent_limit))
    lines.append("")
    lines.extend(_recent_intent_profiles(result, recent_limit))
    lines.append("")
    config = discipline_config or DisciplineConfig()
    lines.extend(_trading_state_model(result, config))
    lines.append("")
    lines.extend(_accumulation_proof_gate(result, current_signal))
    lines.append("")
    lines.extend(_opportunity_radar(result, config))
    lines.append("")
    lines.extend(_trading_action_plan(result, config))
    lines.append("")
    lines.extend(_fills(result))
    lines.append("")
    lines.extend(_tomorrow_scenarios(result))
    if result.skipped_orders:
        lines.append("")
        lines.append("## Skipped Orders")
        lines.extend(f"- {item}" for item in result.skipped_orders)
    return "\n".join(lines)


def _signal_distribution(result: ReplayResult) -> list[str]:
    fund_counts = Counter(signal.fund_signal.value for signal in result.signals)
    tag_counts = Counter(
        tag.value
        for signal in result.signals
        for tag in signal.pattern_tags
    )
    lines = ["## Signal Distribution", "fund_signal:"]
    for key, count in fund_counts.most_common():
        lines.append(f"- {key}: {count}")
    lines.append("pattern_tags:")
    for key, count in tag_counts.most_common():
        lines.append(f"- {key}: {count}")
    return lines


def _strategy_diagnostics(result: ReplayResult, limit: int = 12) -> list[str]:
    diagnostics = diagnose_replay(result)
    lines = ["## Strategy Diagnostics", "Why returns are low:"]
    if diagnostics.findings:
        lines.extend(f"- {item}" for item in diagnostics.findings)
    else:
        lines.append("- no major replay weakness detected")

    lines.extend(
        [
            "",
            "Entry family attribution:",
            "entry_family | trades | win_rate | avg_return | total_pnl",
            "--- | ---: | ---: | ---: | ---:",
        ]
    )
    if not diagnostics.family_summaries:
        lines.append("- | 0 | - | - | -")
    else:
        for item in diagnostics.family_summaries:
            lines.append(
                " | ".join(
                    [
                        item.entry_family,
                        str(item.trades),
                        _pct(item.win_rate_pct),
                        _pct(item.avg_return_pct),
                        f"{item.total_pnl:.2f}",
                    ]
                )
            )

    lines.extend(
        [
            "",
            "Buy timing and detection:",
            "signal_date | entry_date | exit_date | family | return | holding_days | detection",
            "--- | --- | --- | --- | ---: | ---: | ---",
        ]
    )
    if not diagnostics.entries:
        lines.append("- | - | - | no closed entries | - | - | -")
    else:
        for item in diagnostics.entries[-limit:]:
            lines.append(
                " | ".join(
                    [
                        item.signal_date.isoformat() if item.signal_date else "-",
                        item.entry_date.isoformat(),
                        item.exit_date.isoformat(),
                        item.entry_family,
                        _pct(item.return_pct),
                        str(item.holding_days),
                        item.detection,
                    ]
                )
            )

    lines.extend(
        [
            "",
            "Trade thesis stories:",
            "signal_date | entry_date | exit_date | thesis | vpa_archetype | stage | expected_hold | actual_hold | confirmations | warnings | invalidations | return | verdict | holding_evidence",
            "--- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---",
        ]
    )
    if not diagnostics.trade_stories:
        lines.append(
            "- | - | - | no closed entries | - | - | - | - | - | - | - | - | - | -"
        )
    else:
        for story in diagnostics.trade_stories[-limit:]:
            lines.append(
                " | ".join(
                    [
                        story.signal_date or "-",
                        story.entry_date,
                        story.exit_date,
                        story.thesis.buy_type,
                        story.thesis.vpa_archetype,
                        story.thesis.stage,
                        story.thesis.expected_holding_days,
                        str(story.actual_holding_days),
                        str(story.confirmations),
                        str(story.warnings),
                        str(story.invalidations),
                        _pct(story.return_pct),
                        story.verdict,
                        _safe_table_text(story.holding_evidence),
                    ]
                )
            )

    lines.extend(
        [
            "",
            "Position action replay:",
            "signal_date | entry_date | exit_date | action | return | gap | bucket | opening | support_distance | reason",
            "--- | --- | --- | --- | ---: | ---: | ---: | --- | ---: | ---",
        ]
    )
    if not diagnostics.position_action_reviews:
        lines.append("- | - | - | observe | - | - | - | - | - | no closed entries")
    else:
        for review in diagnostics.position_action_reviews[-limit:]:
            bucket = "-" if review.gap_bucket is None else str(review.gap_bucket)
            lines.append(
                " | ".join(
                    [
                        review.signal_date or "-",
                        review.entry_date,
                        review.exit_date,
                        review.position_action,
                        _pct(review.return_pct),
                        _pct(review.gap_pct),
                        bucket,
                        review.opening_classification,
                        _pct(review.support_distance_pct),
                        _safe_table_text(review.action_reason),
                    ]
                )
            )

    lines.extend(
        [
            "",
            "Knowledge hypothesis diagnostics:",
            "entry_date | source | lens | hypothesis | bucket | return | verdict | status",
            "--- | --- | --- | --- | --- | ---: | --- | ---",
        ]
    )
    if not diagnostics.knowledge_hypothesis_reviews:
        lines.append("- | - | - | - | no closed entries | - | - | -")
    else:
        for review in diagnostics.knowledge_hypothesis_reviews[-limit:]:
            lines.append(
                " | ".join(
                    [
                        review.entry_date,
                        review.source_id,
                        review.lens,
                        review.hypothesis_id,
                        _safe_table_text(review.bucket),
                        _pct(review.return_pct),
                        review.verdict,
                        review.diagnostic_status,
                    ]
                )
            )
    return lines


def _volume_price_replay(result: ReplayResult, limit: int = 20) -> list[str]:
    replay = build_volume_price_replay(result)
    lines = [
        "## Historical Volume-Price Replay",
        "- method: replay all available bars with only prior-window volume/range context; fund flow is attached when available.",
        f"- expansion_nodes: {replay.expansion_nodes}",
        f"- shrink_nodes: {replay.shrink_nodes}",
        f"- constructive_nodes: {replay.constructive_nodes}",
        f"- risk_nodes: {replay.risk_nodes}",
    ]
    if replay.latest_node is not None:
        latest = replay.latest_node
        lines.append(
            "- latest_node: "
            f"{latest.trade_date} {latest.node_type} "
            f"volume_ratio={_number(latest.volume_ratio)} "
            f"position={latest.price_position}"
        )

    important = [
        node
        for node in replay.nodes
        if node.node_type != "normal"
    ][-limit:]
    if not important:
        return lines + ["no special volume-price nodes"]

    lines.extend(
        [
            "",
            "date | close | node | volume_state | volume_ratio | position | change | main_flow | main_pct | interpretation",
            "--- | ---: | --- | --- | ---: | --- | ---: | ---: | ---: | ---",
        ]
    )
    for node in important:
        lines.append(
            " | ".join(
                [
                    node.trade_date.isoformat(),
                    _number(node.close),
                    node.node_type,
                    node.volume_state,
                    _number(node.volume_ratio),
                    node.price_position,
                    _pct(node.change_pct),
                    _money(node.main_flow),
                    _pct(node.main_pct),
                    node.interpretation,
                ]
            )
        )
    return lines


def _volume_price_trial_proof(result: ReplayResult, limit: int = 20) -> list[str]:
    decisions = [
        item for item in result.decisions
        if item.observation_type == "volume_price"
    ]
    lines = [
        "## Volume-Price Trial Proof",
        "- method: classify each daily bar with prior-window volume/range context; compare only historical same-node cases already resolved before that day.",
        "- execution_model: signal day close -> infer expected next-open range from prior similar成交额/volume cases -> next trading day open trial buy only when opening behavior is acceptable -> following trading day open timed exit, unless stop/fund-flow risk exits first.",
    ]
    if not decisions:
        return lines + ["- status: volume-probe mode not enabled for this replay."]

    passed = [item for item in decisions if item.volume_probe_passed]
    buys = [item for item in decisions if item.side == "BUY"]
    executed_buys = [
        item for item in result.fills
        if item.reason.startswith("volume_price_trial_entry")
    ]
    opening_cancelled = [
        item for item in result.skipped_orders
        if "volume_price_opening_cancel" in item
    ]
    lines.extend(
        [
            f"- daily_observations: {len(decisions)}",
            f"- passed_history_gate: {len(passed)}",
            f"- trial_buy_decisions: {len(buys)}",
            f"- opening_cancelled: {len(opening_cancelled)}",
            f"- executed_trial_buys: {len(executed_buys)}",
        ]
    )
    latest = decisions[-1]
    lines.append(
        "- latest_trial_state: "
        f"{latest.signal_date} node={latest.volume_node} "
        f"passed={latest.volume_probe_passed} "
        f"cases={latest.volume_probe_cases} "
        f"win={_pct(latest.volume_probe_win_rate_pct)} "
        f"avg={_pct(latest.volume_probe_avg_return_pct)} "
        f"reason={latest.reason}"
    )
    lines.extend(
        [
            "",
            "date | node | side | cases | win_rate | avg_return | reason",
            "--- | --- | --- | ---: | ---: | ---: | ---",
        ]
    )
    for item in decisions[-limit:]:
        lines.append(
            " | ".join(
                [
                    item.signal_date.isoformat(),
                    item.volume_node or "-",
                    item.side or "-",
                    str(item.volume_probe_cases),
                    _pct(item.volume_probe_win_rate_pct),
                    _pct(item.volume_probe_avg_return_pct),
                    item.reason,
                ]
            )
        )
    return lines


def _accumulation_proof_gate(
    result: ReplayResult,
    current_signal: StockSignal | None,
) -> list[str]:
    lines = ["## Disguised Accumulation Proof Gate"]
    if not result.signals:
        return lines + ["no replay signals"]

    proof_signal = current_signal or result.signals[-1]
    source = "current watch signal" if current_signal is not None else "latest replay signal"
    report = build_accumulation_proof_report(
        replay=result,
        current_signal=proof_signal,
        horizon=5,
        min_cases=5,
    )
    seed = report.current_seed
    lines.extend(
        [
            "- method: candidate footprint must be confirmed later; pending proof is not a full-size buy signal.",
            f"- source: {source}",
            f"- current_status: {report.current_status}",
            f"- historical_cases: {len(report.historical_cases)}",
            f"- confirmed_failed_inconclusive: {report.confirmed}/{report.failed}/{report.inconclusive}",
            f"- confirmation_rate_resolved_pct: {_pct(report.confirmation_rate_pct)}",
            f"- conclusion: {report.conclusion}",
            "- trading_gate: wait for at least two of support held, price recovered, main flow reversed.",
        ]
    )
    if seed is not None:
        lines.extend(
            [
                f"- signal_date: {seed.trade_date}",
                f"- candidate_checks: apparent_selling={seed.apparent_selling}, "
                f"small_order_absorption={seed.small_order_absorption}, "
                f"weak_price={seed.weak_price}, failed_breakout={seed.failed_breakout}, "
                f"is_candidate={seed.is_candidate}",
                f"- current_main_flow: {_money(seed.main_flow)}",
                f"- current_small_flow: {_money(seed.small_flow)}",
            ]
        )
    lines.extend(f"- evidence: {item}" for item in report.current_evidence)
    return lines


def _opportunity_radar(
    result: ReplayResult,
    config: DisciplineConfig,
    limit: int = 20,
) -> list[str]:
    opportunities = explain_entry_opportunities(result, config)
    lines = [
        "## Main-Force Opportunity Radar",
        "Entry-like and disguised-accumulation observations are listed here. "
        "Risk gates can block trading, but the signal is still kept for review.",
    ]
    if not opportunities:
        return lines + ["no entry-like observations"]
    lines.append("date | close | fund_signal | tags | status | failed_gates | main_flow | main_pct")
    lines.append("--- | ---: | --- | --- | --- | --- | ---: | ---:")
    for item in opportunities[-limit:]:
        lines.append(
            " | ".join(
                [
                    item.trade_date,
                    _number(item.close),
                    item.fund_signal,
                    item.tags,
                    item.status,
                    ",".join(item.failed_gates) if item.failed_gates else "-",
                    _money(item.main_flow),
                    _pct(item.main_pct),
                ]
            )
        )
    return lines


def _trading_action_plan(result: ReplayResult, config: DisciplineConfig) -> list[str]:
    explanation = explain_latest_action(result, config)
    lines = [
        "## Trading Action Plan",
        f"- current_position: {explanation.position_state}",
        f"- action: {explanation.action}",
        f"- summary: {explanation.summary}",
        "",
        "Buy checklist:",
        "condition | status | detail",
        "--- | --- | ---",
    ]
    lines.extend(
        f"{check.name} | {check.status} | {check.detail}"
        for check in explanation.buy_checks
    )
    lines.extend(
        [
            "",
            "Sell checklist:",
            "condition | status | detail",
            "--- | --- | ---",
        ]
    )
    lines.extend(
        f"{check.name} | {check.status} | {check.detail}"
        for check in explanation.sell_checks
    )
    lines.append("")
    lines.append("Next steps:")
    lines.extend(f"- {step}" for step in explanation.next_steps)
    return lines


def _target_graph(result: ReplayResult, target_annual_return: float) -> list[str]:
    assessment = assess_target_return(result, target_annual_return)
    lines = [
        "## Target Return Knowledge Graph",
        f"- target_annual_return_pct: {assessment.target_annual_return_pct:.2f}%",
        f"- actual_annualized_return_pct: {assessment.actual_annualized_return_pct:.2f}%",
        f"- target_period_return_pct: {assessment.target_period_return_pct:.2f}%",
        f"- current_period_return_pct: {assessment.current_period_return_pct:.2f}%",
        f"- target_final_value: {assessment.target_final_value:.2f}",
        f"- current_final_value: {assessment.current_final_value:.2f}",
        f"- gap_amount: {assessment.gap_amount:.2f}",
        f"- conclusion: {assessment.conclusion}",
        "",
        "node | status | score | detail",
        "--- | --- | ---: | ---",
    ]
    for node in assessment.nodes:
        lines.append(
            " | ".join(
                [
                    node.label,
                    node.status,
                    f"{node.score:.1f}",
                    node.detail,
                ]
            )
        )
    return lines


def _return_estimate(result: ReplayResult) -> list[str]:
    _, estimate = estimate_returns(result.fills, result.initial_cash)
    lines = [
        "## Return Estimate",
        "- method: closed paper-trade expectancy from this replay; not a forecast.",
        f"- sample_quality: {estimate.sample_quality}",
        f"- closed_round_trips: {estimate.closed_trades}",
    ]
    if estimate.closed_trades == 0:
        lines.append("- estimate: no closed trades, keep observing.")
        return lines
    lines.extend(
        [
            f"- win_rate_pct: {_pct(estimate.win_rate_pct)}",
            f"- expectancy_per_trade_pct: {_pct(estimate.expectancy_pct)}",
            f"- account_expectancy_per_trade_pct: {_pct(estimate.account_expectancy_pct)}",
            f"- avg_win_pct: {_pct(estimate.avg_win_pct)}",
            f"- avg_loss_pct: {_pct(estimate.avg_loss_pct)}",
            f"- best_trade_pct: {_pct(estimate.best_trade_pct)}",
            f"- worst_trade_pct: {_pct(estimate.worst_trade_pct)}",
            f"- profit_factor: {_number(estimate.profit_factor)}",
            f"- avg_holding_days: {_number(estimate.avg_holding_days)}",
        ]
    )
    if estimate.sample_quality == "too_small_do_not_project":
        lines.append("- interpretation: sample is too small; do not use it for capital sizing.")
    elif estimate.expectancy_pct is not None and estimate.expectancy_pct <= 0:
        lines.append("- interpretation: observed expectancy is negative; block real-money allocation.")
    else:
        lines.append("- interpretation: positive observed expectancy still needs broader-symbol validation.")
    return lines


def _recent_signals(result: ReplayResult, limit: int) -> list[str]:
    lines = ["## Recent Signals"]
    if not result.signals:
        return lines + ["no signals"]
    lines.append(
        "date | close | fund_signal | tags | main_flow | main_pct | change_pct | "
        "volume_ratio | turnover"
    )
    lines.append("--- | ---: | --- | --- | ---: | ---: | ---: | ---: | ---:")
    for signal in result.signals[-limit:]:
        quote = signal.quote
        flow = signal.fund_flow
        tags = ",".join(tag.value for tag in signal.pattern_tags)
        lines.append(
            " | ".join(
                [
                    signal.timestamp.date().isoformat(),
                    _number(quote.price if quote else None),
                    signal.fund_signal.value,
                    tags,
                    _money(flow.main_net_inflow),
                    _pct(flow.main_net_inflow_pct),
                    _pct(flow.change_pct),
                    _number(quote.volume_ratio if quote else None),
                    _pct(flow.turnover_rate),
                ]
            )
        )
    return lines


def _fills(result: ReplayResult) -> list[str]:
    lines = ["## Paper Fills"]
    if not result.fills:
        return lines + ["no fills"]
    lines.append("date | side | quantity | price | reason")
    lines.append("--- | --- | ---: | ---: | ---")
    for fill in result.fills:
        lines.append(
            " | ".join(
                [
                    fill.trade_date.isoformat(),
                    fill.side.value,
                    str(fill.quantity),
                    f"{fill.price:.2f}",
                    fill.reason,
                ]
            )
        )
    return lines


def _recent_intent_profiles(result: ReplayResult, limit: int) -> list[str]:
    lines = ["## Recent Main-Force Intent Proxy"]
    profiles = [
        signal.intent_profile
        for signal in result.signals
        if signal.intent_profile is not None
    ]
    if not profiles:
        return lines + ["no profiles"]
    lines.append(
        "date | stage | daily | weekly | monthly | vwap60 | close_vs_vwap60 | "
        "flow5 | flow10 | acc | markup | dist"
    )
    lines.append("--- | --- | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---:")
    for profile in profiles[-limit:]:
        lines.append(
            " | ".join(
                [
                    profile.trade_date.isoformat(),
                    profile.stage,
                    profile.daily_trend,
                    profile.weekly_trend,
                    profile.monthly_trend,
                    _number(profile.vwap_60),
                    _pct(profile.close_vs_vwap_60_pct),
                    _money(profile.main_flow_5),
                    _money(profile.main_flow_10),
                    f"{profile.accumulation_score:.1f}",
                    f"{profile.markup_score:.1f}",
                    f"{profile.distribution_score:.1f}",
                ]
            )
        )
    return lines


def _trading_state_model(result: ReplayResult, config: DisciplineConfig) -> list[str]:
    lines = ["## Multi-Node Trading State Model"]
    if not result.signals:
        return lines + ["no signals"]

    state = build_trading_state_model(result, config)
    fund = state.fund_data
    action = state.behavior_action
    lines.extend(
        [
            f"- trading_mode: {state.trading_mode}",
            f"- buy_state: {state.buy_state}",
            f"- sell_state: {state.sell_state}",
            f"- risk_state: {state.risk_state}",
            f"- summary: {state.summary}",
            "",
            "Fund data model:",
            f"- data_coverage_pct: {fund.data_coverage_pct:.2f}%",
            f"- flow_bias: {fund.flow_bias}",
            f"- flow_consistency_pct: {fund.flow_consistency_pct:.2f}%",
            f"- latest_main_flow: {_money(fund.latest_main_flow)}",
            f"- latest_main_pct: {_pct(fund.latest_main_pct)}",
            f"- rolling_flow_3_5_10: {_money(fund.flow_3)} / {_money(fund.flow_5)} / {_money(fund.flow_10)}",
            f"- large_small_divergence: {fund.large_small_divergence}",
            f"- price_flow_divergence: {fund.price_flow_divergence}",
            "",
            "Behavior action model:",
            f"- phase: {action.phase}",
            f"- action_bias: {action.action_bias}",
            f"- confidence: {action.confidence:.2f}",
            f"- buy_pressure_score: {action.buy_pressure_score:.2f}",
            f"- sell_pressure_score: {action.sell_pressure_score:.2f}",
            f"- pattern: {action.pattern}",
            "",
            "node | status | score | detail",
            "--- | --- | ---: | ---",
        ]
    )
    for node in state.nodes:
        lines.append(
            " | ".join(
                [
                    node.label,
                    node.status,
                    f"{node.score:.1f}",
                    node.detail,
                ]
            )
        )
    lines.append("")
    lines.append("Next steps:")
    lines.extend(f"- {step}" for step in state.next_steps)
    return lines


def _tomorrow_scenarios(result: ReplayResult) -> list[str]:
    lines = ["## Next-Day Scenario Checklist"]
    if not result.signals:
        return lines + ["No fund-flow signal available for scenario generation."]

    latest = result.signals[-1]
    quote = latest.quote
    flow = latest.fund_flow
    if quote is None:
        return lines + ["No quote available for latest signal."]

    lines.extend(
        [
            f"- latest_close: {quote.price:.2f}",
            f"- latest_fund_signal: {latest.fund_signal.value}",
            f"- latest_pattern_tags: {','.join(tag.value for tag in latest.pattern_tags)}",
            f"- main_net_inflow: {flow.main_net_inflow:.0f}",
            f"- main_net_inflow_pct: {_pct(flow.main_net_inflow_pct)}",
        ]
    )
    if quote.high_20 is not None:
        lines.append(f"- previous_20d_high: {quote.high_20:.2f}")
    if quote.low_20 is not None:
        lines.append(f"- previous_20d_low: {quote.low_20:.2f}")
    if latest.intent_profile is not None:
        profile = latest.intent_profile
        lines.extend(
            [
                f"- stage: {profile.stage}",
                f"- daily_weekly_monthly: {profile.daily_trend}/{profile.weekly_trend}/{profile.monthly_trend}",
                f"- vwap60_cost_proxy: {_number(profile.vwap_60)}",
                f"- close_vs_vwap60: {_pct(profile.close_vs_vwap_60_pct)}",
                f"- accumulation_score: {profile.accumulation_score:.1f}",
                f"- markup_score: {profile.markup_score:.1f}",
                f"- distribution_score: {profile.distribution_score:.1f}",
            ]
        )

    lines.extend(
        [
            "- stronger case: price reclaims the prior high area with positive main flow and expanding amount.",
            "- neutral case: price holds above latest low but main flow remains mixed or weak.",
            "- weaker case: price breaks latest low while super-large/large orders continue net outflow.",
        ]
    )
    return lines


def _money(value: float | None) -> str:
    if value is None:
        return "-"
    abs_value = abs(value)
    if abs_value >= 100000000:
        return f"{value / 100000000:.2f}e8"
    if abs_value >= 10000:
        return f"{value / 10000:.2f}w"
    return f"{value:.2f}"


def _pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}%"


def _safe_table_text(value: object) -> str:
    return str(value).replace("|", "/")


def _number(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}"
