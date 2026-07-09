"""Historical replay for fund-flow monitor signals and paper trading."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date

from wealth_lab.accumulation_proof import build_point_in_time_proof_context
from wealth_lab.features import build_quote_from_bar
from wealth_lab.intent_features import build_main_force_profile
from wealth_lab.models import Bar, Fill, FundFlowSnapshot, PortfolioSnapshot, StockSignal
from wealth_lab.models import MainForceProfile
from wealth_lab.paper import PaperBroker
from wealth_lab.signal_engine import FundSignalEngine, SignalThresholds
from wealth_lab.trade_discipline import TradeDecision, TradeDiscipline
from wealth_lab.volume_probe import VolumeProbeContext


@dataclass(frozen=True)
class ReplayDecision:
    """A signal-day decision and optional execution information."""

    signal_date: date
    symbol: str
    fund_signal: str
    pattern_tags: tuple[str, ...]
    side: str | None
    reason: str
    proof_status: str | None = None
    proof_confirmation_rate_pct: float | None = None
    proof_resolved_cases: int = 0
    observation_type: str = "fund_flow"
    volume_node: str | None = None
    volume_probe_passed: bool | None = None
    volume_probe_cases: int = 0
    volume_probe_win_rate_pct: float | None = None
    volume_probe_avg_return_pct: float | None = None


@dataclass(frozen=True)
class ReplayResult:
    """Result from one historical replay run."""

    symbol: str
    name: str
    bars_count: int
    fund_flows_count: int
    first_bar_date: date
    last_bar_date: date
    signals: list[StockSignal]
    decisions: list[ReplayDecision]
    fills: list[Fill]
    equity_curve: list[PortfolioSnapshot]
    missing_fund_flow_dates: list[date]
    skipped_orders: list[str]
    initial_cash: float
    final_value: float
    total_return: float
    max_drawdown: float
    bars: list[Bar] = field(default_factory=list)
    fund_flows: list[FundFlowSnapshot] = field(default_factory=list)


@dataclass(frozen=True)
class _VolumeReplayDecision:
    """Internal pair of replay record and executable trade decision."""

    record: ReplayDecision
    trade_decision: TradeDecision
    context: VolumeProbeContext
    intent_profile: MainForceProfile | None = None


@dataclass(frozen=True)
class _VolumeConfirmationObservation:
    """Observed breakout waiting for post-signal confirmation."""

    decision: TradeDecision
    signal_index: int
    context: VolumeProbeContext
    intent_profile: MainForceProfile | None


@dataclass(frozen=True)
class _PreBreakoutWatch:
    """A non-breakout node waiting for later breakout confirmation."""

    signal_index: int
    context: VolumeProbeContext


class HistoricalReplayRunner:
    """Replay one stock with historical bars and daily fund-flow snapshots."""

    def __init__(
        self,
        bars: list[Bar],
        fund_flows: list[FundFlowSnapshot],
        initial_cash: float = 100000.0,
        discipline: TradeDiscipline | None = None,
    ) -> None:
        if not bars:
            raise ValueError("bars must not be empty")
        self.bars = sorted(bars, key=lambda item: item.trade_date)
        self.fund_flows = sorted(fund_flows, key=lambda item: item.timestamp)
        self.initial_cash = initial_cash
        self.discipline = discipline or TradeDiscipline()
        self.engine = FundSignalEngine(
            SignalThresholds(require_sector_confirmation=False)
        )

    def run(self) -> ReplayResult:
        """Run historical replay and paper-trading simulation."""

        broker = PaperBroker(self.initial_cash)
        latest_prices: dict[str, float] = {}
        flows_by_date = {
            flow.timestamp.date(): flow
            for flow in self.fund_flows
        }
        symbol = self.bars[0].symbol
        name = _name_from_flows(self.fund_flows, symbol)

        signals: list[StockSignal] = []
        decisions: list[ReplayDecision] = []
        equity_curve: list[PortfolioSnapshot] = []
        missing_flow_dates: list[date] = []
        skipped_orders: list[str] = []
        pending_decision: TradeDecision | None = None
        pending_signal_index: int | None = None
        pending_volume_observation: _VolumeConfirmationObservation | None = None
        pending_pre_breakout_watch: _PreBreakoutWatch | None = None

        for index, bar in enumerate(self.bars):
            latest_prices[symbol] = bar.open
            if pending_decision and pending_decision.is_trade:
                executable_decision = _confirm_pending_opening(
                    discipline=self.discipline,
                    pending_decision=pending_decision,
                    bars=self.bars,
                    pending_signal_index=pending_signal_index,
                    execution_index=index,
                )
                if not executable_decision.is_trade:
                    skipped_orders.append(
                        f"{bar.trade_date}: {executable_decision.reason}"
                    )
                order = self.discipline.create_order(
                    symbol=symbol,
                    decision=executable_decision,
                    broker=broker,
                    latest_prices=latest_prices,
                    execution_price=bar.open,
                )
                if order is not None:
                    try:
                        broker.execute_market_order(order, bar.open, bar.trade_date)
                    except ValueError as exc:
                        skipped_orders.append(f"{bar.trade_date}: {exc}")
            pending_decision = None
            pending_signal_index = None

            latest_prices[symbol] = bar.close
            flow = flows_by_date.get(bar.trade_date)
            if flow is None:
                missing_flow_dates.append(bar.trade_date)
            else:
                previous_bars = self.bars[:index]
                enriched_flow = _enrich_flow(flow, bar)
                quote = build_quote_from_bar(
                    bar=bar,
                    name=name,
                    previous_bars=previous_bars,
                    fund_flow=enriched_flow,
                    provider="historical-replay",
                )
                signal = self.engine.evaluate(
                    fund_flow=enriched_flow,
                    quote=quote,
                    sector_flow=None,
                    recent_bars=previous_bars[-20:],
                )
                profile = build_main_force_profile(self.bars, self.fund_flows, index)
                signal = replace(signal, intent_profile=profile)
                signals.append(signal)

                proof_context = build_point_in_time_proof_context(
                    signals=signals,
                    index=len(signals) - 1,
                    horizon=self.discipline.config.accumulation_proof_horizon,
                    min_cases=self.discipline.config.min_accumulation_proof_cases,
                    min_confirmation_rate_pct=(
                        self.discipline.config.min_accumulation_proof_rate_pct
                    ),
                )
                decision = self.discipline.decide(signal, broker, proof_context)
                decisions.append(
                    ReplayDecision(
                        signal_date=bar.trade_date,
                        symbol=symbol,
                        fund_signal=signal.fund_signal.value,
                        pattern_tags=tuple(tag.value for tag in signal.pattern_tags),
                        side=decision.side.value if decision.side else None,
                        reason=decision.reason,
                        proof_status=proof_context.status,
                        proof_confirmation_rate_pct=(
                            proof_context.confirmation_rate_pct
                        ),
                        proof_resolved_cases=proof_context.resolved,
                    )
                )
                if decision.is_trade and index < len(self.bars) - 1:
                    pending_decision = decision
                    pending_signal_index = index

            if self.discipline.config.enable_volume_price_probe:
                if pending_volume_observation is not None:
                    observation_decision = _volume_confirmation_observation_decision(
                        discipline=self.discipline,
                        observation=pending_volume_observation,
                        bars=self.bars,
                        flows_by_date=flows_by_date,
                        index=index,
                        symbol=symbol,
                        pending_decision=pending_decision,
                        is_last_bar=index >= len(self.bars) - 1,
                    )
                    decisions.append(observation_decision.record)
                    pending_volume_observation = None
                    if (
                        observation_decision.trade_decision.is_trade
                        and index < len(self.bars) - 1
                        and pending_decision is None
                    ):
                        pending_decision = observation_decision.trade_decision
                        pending_signal_index = index

                main_flow = flow.main_net_inflow if flow is not None else None
                volume_decision = _volume_probe_decision(
                    discipline=self.discipline,
                    bars=self.bars,
                    fund_flows=self.fund_flows,
                    index=index,
                    symbol=symbol,
                    broker=broker,
                    pending_decision=pending_decision,
                    is_last_bar=index >= len(self.bars) - 1,
                    main_flow=main_flow,
                )
                watch_handoff_consumed = False
                if pending_pre_breakout_watch is not None:
                    watch_decision = _pre_breakout_watch_decision(
                        discipline=self.discipline,
                        watch=pending_pre_breakout_watch,
                        confirmation=volume_decision,
                        bars=self.bars,
                        index=index,
                        symbol=symbol,
                        main_flow=main_flow,
                        pending_decision=pending_decision,
                        is_last_bar=index >= len(self.bars) - 1,
                    )
                    if watch_decision is not None:
                        decisions.append(watch_decision.record)
                        if (
                            watch_decision.trade_decision.is_trade
                            and index < len(self.bars) - 1
                            and pending_decision is None
                        ):
                            pending_decision = watch_decision.trade_decision
                            pending_signal_index = index
                            watch_handoff_consumed = True
                        if (
                            "volume_price_pre_breakout_watch_hold"
                            not in watch_decision.trade_decision.reason
                        ):
                            pending_pre_breakout_watch = None
                if (
                    volume_decision.trade_decision.is_trade
                    and volume_decision.context.node.node_type == "volume_breakout"
                ):
                    pending_pre_breakout_watch = None
                if self.discipline.should_observe_volume_breakout_confirmation_entry(
                    volume_decision.trade_decision,
                    volume_decision.intent_profile,
                ):
                    decisions.append(
                        _volume_confirmation_observation_record(volume_decision)
                    )
                    pending_volume_observation = _VolumeConfirmationObservation(
                        decision=volume_decision.trade_decision,
                        signal_index=index,
                        context=volume_decision.context,
                        intent_profile=volume_decision.intent_profile,
                    )
                else:
                    if not watch_handoff_consumed:
                        decisions.append(volume_decision.record)
                    if (
                        volume_decision.trade_decision.is_trade
                        and index < len(self.bars) - 1
                        and pending_decision is None
                    ):
                        pending_decision = volume_decision.trade_decision
                        pending_signal_index = index
                if (
                    pending_pre_breakout_watch is None
                    and pending_decision is None
                    and not volume_decision.trade_decision.is_trade
                    and index < len(self.bars) - 1
                    and self.discipline.should_add_pre_breakout_watch(
                        volume_decision.context,
                        broker,
                        symbol,
                    )
                ):
                    pending_pre_breakout_watch = _PreBreakoutWatch(
                        signal_index=index,
                        context=volume_decision.context,
                    )
                    decisions.append(
                        _pre_breakout_watch_record(
                            symbol=symbol,
                            bars=self.bars,
                            index=index,
                            context=volume_decision.context,
                        )
                    )
            equity_curve.append(broker.snapshot(bar.trade_date, latest_prices))

        final_value = equity_curve[-1].total_value
        return ReplayResult(
            symbol=symbol,
            name=name,
            bars_count=len(self.bars),
            fund_flows_count=len(self.fund_flows),
            first_bar_date=self.bars[0].trade_date,
            last_bar_date=self.bars[-1].trade_date,
            signals=signals,
            decisions=decisions,
            fills=list(broker.fills),
            equity_curve=equity_curve,
            missing_fund_flow_dates=missing_flow_dates,
            skipped_orders=skipped_orders,
            initial_cash=self.initial_cash,
            final_value=final_value,
            total_return=(final_value / self.initial_cash) - 1,
            max_drawdown=_max_drawdown([snapshot.total_value for snapshot in equity_curve]),
            bars=list(self.bars),
            fund_flows=list(self.fund_flows),
        )


def _enrich_flow(flow: FundFlowSnapshot, bar: Bar) -> FundFlowSnapshot:
    return replace(
        flow,
        amount=flow.amount if flow.amount is not None else bar.amount,
        turnover_rate=flow.turnover_rate
        if flow.turnover_rate is not None
        else bar.turnover_rate,
        change_pct=flow.change_pct if flow.change_pct is not None else bar.change_pct,
    )


def _volume_probe_decision(
    *,
    discipline: TradeDiscipline,
    bars: list[Bar],
    fund_flows: list[FundFlowSnapshot],
    index: int,
    symbol: str,
    broker: PaperBroker,
    pending_decision: TradeDecision | None,
    is_last_bar: bool,
    main_flow: float | None,
) -> _VolumeReplayDecision:
    context = discipline.build_volume_probe_context(bars, index)
    intent_profile: MainForceProfile | None = None
    if pending_decision is not None and pending_decision.is_trade:
        decision = TradeDecision(
            side=None,
            reason="volume_price_trial_blocked: pending_signal_trade",
        )
    else:
        exit_decision = discipline.decide_volume_probe_exit(
            symbol,
            broker,
            bars=bars,
            current_index=index,
            main_flow=main_flow,
        )
        intent_profile = (
            build_main_force_profile(bars, fund_flows, index)
            if discipline.config.enable_volume_price_intent_filter
            else None
        )
        decision = (
            exit_decision
            if exit_decision.is_trade
            else discipline.decide_volume_probe(
                symbol,
                context,
                broker,
                intent_profile=intent_profile,
            )
        )
    if is_last_bar and decision.is_trade:
        decision = TradeDecision(
            side=None,
            reason="volume_price_trial_blocked: no_next_bar_for_execution",
        )
    return _VolumeReplayDecision(
        record=ReplayDecision(
            signal_date=bars[index].trade_date,
            symbol=symbol,
            fund_signal="volume_price",
            pattern_tags=(context.node.node_type,),
            side=decision.side.value if decision.side else None,
            reason=decision.reason,
            observation_type="volume_price",
            volume_node=context.node.node_type,
            volume_probe_passed=context.passed,
            volume_probe_cases=context.resolved_cases,
            volume_probe_win_rate_pct=context.win_rate_pct,
            volume_probe_avg_return_pct=context.avg_return_pct,
        ),
        trade_decision=decision,
        context=context,
        intent_profile=intent_profile,
    )


def _pre_breakout_watch_record(
    *,
    symbol: str,
    bars: list[Bar],
    index: int,
    context: VolumeProbeContext,
) -> ReplayDecision:
    return ReplayDecision(
        signal_date=bars[index].trade_date,
        symbol=symbol,
        fund_signal="volume_price",
        pattern_tags=(context.node.node_type,),
        side=None,
        reason=(
            "volume_price_pre_breakout_watch: "
            f"node={context.node.node_type} "
            f"cases={context.resolved_cases} "
            f"win={_fmt_optional(context.win_rate_pct)}% "
            f"avg={_fmt_optional(context.avg_return_pct)}%; "
            f"{context.reason}"
        ),
        observation_type="volume_price",
        volume_node=context.node.node_type,
        volume_probe_passed=context.passed,
        volume_probe_cases=context.resolved_cases,
        volume_probe_win_rate_pct=context.win_rate_pct,
        volume_probe_avg_return_pct=context.avg_return_pct,
    )


def _pre_breakout_watch_decision(
    *,
    discipline: TradeDiscipline,
    watch: _PreBreakoutWatch,
    confirmation: _VolumeReplayDecision,
    bars: list[Bar],
    index: int,
    symbol: str,
    main_flow: float | None,
    pending_decision: TradeDecision | None,
    is_last_bar: bool,
) -> _VolumeReplayDecision | None:
    age = index - watch.signal_index
    max_age = max(1, discipline.config.volume_price_pre_breakout_max_age_bars)
    if pending_decision is not None and pending_decision.is_trade:
        decision = TradeDecision(
            side=None,
            reason=(
                "volume_price_pre_breakout_watch_cancel: "
                f"pending_signal_trade watch_node={watch.context.node.node_type} "
                f"age={age}"
            ),
        )
    elif age > max_age or confirmation.context.node.node_type == "volume_breakout":
        decision = discipline.confirm_pre_breakout_watchlist_entry(
            symbol=symbol,
            watch_context=watch.context,
            confirmation_context=confirmation.context,
            bars=bars,
            watch_index=watch.signal_index,
            confirmation_index=index,
            main_flow=main_flow,
        )
    else:
        return None

    if is_last_bar and decision.is_trade:
        decision = TradeDecision(
            side=None,
            reason=(
                "volume_price_pre_breakout_watch_cancel: "
                f"no_next_bar_for_execution; original={decision.reason}"
            ),
        )
    return _VolumeReplayDecision(
        record=ReplayDecision(
            signal_date=bars[index].trade_date,
            symbol=symbol,
            fund_signal="volume_price",
            pattern_tags=(watch.context.node.node_type, confirmation.context.node.node_type),
            side=decision.side.value if decision.side else None,
            reason=decision.reason,
            observation_type="volume_price",
            volume_node=confirmation.context.node.node_type,
            volume_probe_passed=confirmation.context.passed,
            volume_probe_cases=confirmation.context.resolved_cases,
            volume_probe_win_rate_pct=confirmation.context.win_rate_pct,
            volume_probe_avg_return_pct=confirmation.context.avg_return_pct,
        ),
        trade_decision=decision,
        context=confirmation.context,
        intent_profile=confirmation.intent_profile,
    )


def _volume_confirmation_observation_record(
    volume_decision: _VolumeReplayDecision,
) -> ReplayDecision:
    stage = (
        volume_decision.intent_profile.stage
        if volume_decision.intent_profile is not None
        else "unknown"
    )
    record = volume_decision.record
    return ReplayDecision(
        signal_date=record.signal_date,
        symbol=record.symbol,
        fund_signal=record.fund_signal,
        pattern_tags=record.pattern_tags,
        side=None,
        reason=(
            "volume_price_breakout_observe: "
            f"stage={stage} wait_for_confirmation; "
            f"original={volume_decision.trade_decision.reason}"
        ),
        observation_type=record.observation_type,
        volume_node=record.volume_node,
        volume_probe_passed=record.volume_probe_passed,
        volume_probe_cases=record.volume_probe_cases,
        volume_probe_win_rate_pct=record.volume_probe_win_rate_pct,
        volume_probe_avg_return_pct=record.volume_probe_avg_return_pct,
    )


def _volume_confirmation_observation_decision(
    *,
    discipline: TradeDiscipline,
    observation: _VolumeConfirmationObservation,
    bars: list[Bar],
    flows_by_date: dict[date, FundFlowSnapshot],
    index: int,
    symbol: str,
    pending_decision: TradeDecision | None,
    is_last_bar: bool,
) -> _VolumeReplayDecision:
    if pending_decision is not None and pending_decision.is_trade:
        decision = TradeDecision(
            side=None,
            reason=(
                "volume_price_breakout_confirmation_cancel: "
                f"pending_signal_trade; original={observation.decision.reason}"
            ),
        )
    else:
        flow = flows_by_date.get(bars[index].trade_date)
        main_flow = flow.main_net_inflow if flow is not None else None
        decision = discipline.confirm_volume_breakout_confirmation_entry(
            observation.decision,
            bars=bars,
            signal_index=observation.signal_index,
            confirmation_index=index,
            main_flow=main_flow,
        )
        if is_last_bar and decision.is_trade:
            decision = TradeDecision(
                side=None,
                reason=(
                    "volume_price_breakout_confirmation_cancel: "
                    f"no_next_bar_for_execution; original={decision.reason}"
                ),
            )
    return _VolumeReplayDecision(
        record=ReplayDecision(
            signal_date=bars[index].trade_date,
            symbol=symbol,
            fund_signal="volume_price",
            pattern_tags=(observation.context.node.node_type,),
            side=decision.side.value if decision.side else None,
            reason=decision.reason,
            observation_type="volume_price",
            volume_node=observation.context.node.node_type,
            volume_probe_passed=observation.context.passed,
            volume_probe_cases=observation.context.resolved_cases,
            volume_probe_win_rate_pct=observation.context.win_rate_pct,
            volume_probe_avg_return_pct=observation.context.avg_return_pct,
        ),
        trade_decision=decision,
        context=observation.context,
        intent_profile=observation.intent_profile,
    )


def _confirm_pending_opening(
    *,
    discipline: TradeDiscipline,
    pending_decision: TradeDecision,
    bars: list[Bar],
    pending_signal_index: int | None,
    execution_index: int,
) -> TradeDecision:
    if pending_signal_index is None:
        return pending_decision
    if not pending_decision.reason.startswith("volume_price_trial_entry"):
        return pending_decision
    return discipline.confirm_volume_probe_opening(
        decision=pending_decision,
        bars=bars,
        signal_index=pending_signal_index,
        execution_index=execution_index,
    )


def _name_from_flows(flows: list[FundFlowSnapshot], symbol: str) -> str:
    for flow in flows:
        if flow.name:
            return flow.name
    return symbol


def _max_drawdown(values: list[float]) -> float:
    peak = values[0]
    worst = 0.0
    for value in values:
        if value > peak:
            peak = value
        drawdown = (peak - value) / peak if peak else 0.0
        worst = max(worst, drawdown)
    return worst


def _fmt_optional(value: float | None) -> str:
    if value is None:
        return "NA"
    return f"{value:.2f}"
