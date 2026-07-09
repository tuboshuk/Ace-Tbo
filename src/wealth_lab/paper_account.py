"""Monthly paper-account replay reporting."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path

from wealth_lab.models import Bar, Fill, Order, OrderSide, PortfolioSnapshot
from wealth_lab.paper import PaperBroker
from wealth_lab.replay import HistoricalReplayRunner, ReplayResult
from wealth_lab.trade_discipline import TradeDiscipline
from wealth_lab.training import (
    TrainingCandidate,
    TrainingFundFlowFetcher,
    TrainingHistoricalBarFetcher,
    default_training_candidates,
)


@dataclass(frozen=True)
class MonthlyPaperAccountRow:
    """One month of marked-to-market paper-account performance."""

    month: str
    first_trade_date: date
    last_trade_date: date
    start_value: float
    end_value: float
    return_pct: float
    buy_fills: int
    sell_fills: int
    holding_days: int
    cash_days: int
    avg_capital_utilization_pct: float
    target_gap_pct: float
    max_drawdown_pct: float


@dataclass(frozen=True)
class PaperAccountGoalModel:
    """Descriptive account target and cost assumptions for reports."""

    monthly_target_return_pct: float = 8.0
    cost_budget_pct: float = 30.0

    @property
    def monthly_cost_budget_return_pct(self) -> float:
        return self.monthly_target_return_pct * self.cost_budget_pct / 100


@dataclass(frozen=True)
class PaperAccountReport:
    """A single-symbol paper-account replay and its monthly account rows."""

    run_id: str
    symbol: str
    name: str
    strategy: str
    requested_start: date
    requested_end: date
    initial_cash: float
    final_value: float
    total_return_pct: float
    max_drawdown_pct: float
    bars_count: int
    fund_flows_count: int
    missing_fund_flow_dates: int
    goal_model: PaperAccountGoalModel
    monthly_rows: tuple[MonthlyPaperAccountRow, ...]
    fills: tuple[Fill, ...]
    output_path: Path | None = None


@dataclass(frozen=True)
class PortfolioPaperAccountConfig:
    """Portfolio-level execution constraints for paper-account aggregation."""

    max_positions: int = 5
    min_buy_weight: float = 0.05
    max_position_weight: float = 0.20


@dataclass(frozen=True)
class PortfolioReplaySummary:
    """One symbol's replay coverage inside a portfolio paper account."""

    symbol: str
    name: str
    bars_count: int
    fund_flows_count: int
    missing_fund_flow_dates: int
    source_fills: int


@dataclass(frozen=True)
class PortfolioPaperAccountReport:
    """A multi-symbol paper account with one shared cash pool."""

    run_id: str
    symbols: tuple[str, ...]
    strategy: str
    requested_start: date
    requested_end: date
    initial_cash: float
    final_value: float
    total_return_pct: float
    max_drawdown_pct: float
    config: PortfolioPaperAccountConfig
    goal_model: PaperAccountGoalModel
    monthly_rows: tuple[MonthlyPaperAccountRow, ...]
    fills: tuple[Fill, ...]
    skipped_orders: tuple[str, ...]
    replay_summaries: tuple[PortfolioReplaySummary, ...]
    errors: tuple[str, ...] = ()
    output_path: Path | None = None


def run_single_symbol_paper_account(
    *,
    symbol: str,
    start: date,
    end: date,
    initial_cash: float,
    output_dir: Path,
    candidate: TrainingCandidate | None = None,
    goal_model: PaperAccountGoalModel | None = None,
) -> PaperAccountReport:
    """Fetch data, replay one strategy, and persist a monthly paper report."""

    if start > end:
        raise ValueError("start must be on or before end")
    if initial_cash <= 0:
        raise ValueError("initial_cash must be positive")

    selected = candidate or default_training_candidates()[0]
    historical_fetcher = TrainingHistoricalBarFetcher()
    fund_fetcher = TrainingFundFlowFetcher()
    try:
        bars = historical_fetcher.fetch_daily_bars(symbol, start, end)
        fund_flows = [
            item
            for item in fund_fetcher.fetch_history(symbol)
            if start <= item.timestamp.date() <= end
        ]
    finally:
        historical_fetcher.close()

    replay = HistoricalReplayRunner(
        bars=bars,
        fund_flows=fund_flows,
        initial_cash=initial_cash,
        discipline=TradeDiscipline(selected.config),
    ).run()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{run_id}-{symbol}-paper-account.md"
    report = build_paper_account_report(
        replay=replay,
        strategy=selected.name,
        requested_start=start,
        requested_end=end,
        run_id=run_id,
        output_path=output_path,
        goal_model=goal_model or PaperAccountGoalModel(),
    )
    output_path.write_text(render_paper_account_report(report), encoding="utf-8")
    return report


def run_portfolio_paper_account(
    *,
    symbols: list[str],
    start: date,
    end: date,
    initial_cash: float,
    output_dir: Path,
    config: PortfolioPaperAccountConfig | None = None,
    candidate: TrainingCandidate | None = None,
    goal_model: PaperAccountGoalModel | None = None,
) -> PortfolioPaperAccountReport:
    """Fetch data, replay symbols, and persist one shared portfolio report."""

    if not symbols:
        raise ValueError("symbols must not be empty")
    if start > end:
        raise ValueError("start must be on or before end")
    if initial_cash <= 0:
        raise ValueError("initial_cash must be positive")

    selected = candidate or default_training_candidates()[0]
    selected_config = config or PortfolioPaperAccountConfig()
    _validate_portfolio_config(selected_config)
    replays: list[ReplayResult] = []
    errors: list[str] = []
    historical_fetcher = TrainingHistoricalBarFetcher()
    fund_fetcher = TrainingFundFlowFetcher()
    try:
        for symbol in symbols:
            try:
                bars = historical_fetcher.fetch_daily_bars(symbol, start, end)
                fund_flows = [
                    item
                    for item in fund_fetcher.fetch_history(symbol)
                    if start <= item.timestamp.date() <= end
                ]
                replays.append(
                    HistoricalReplayRunner(
                        bars=bars,
                        fund_flows=fund_flows,
                        initial_cash=initial_cash,
                        discipline=TradeDiscipline(selected.config),
                    ).run()
                )
            except Exception as exc:  # noqa: BLE001 - data providers vary.
                errors.append(f"{symbol}: {exc}")
    finally:
        historical_fetcher.close()

    if not replays:
        raise RuntimeError("no symbols produced valid replays")

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{run_id}-portfolio-paper-account.md"
    report = build_portfolio_paper_account_report(
        replays=tuple(replays),
        strategy=selected.name,
        requested_start=start,
        requested_end=end,
        initial_cash=initial_cash,
        config=selected_config,
        run_id=run_id,
        errors=tuple(errors),
        output_path=output_path,
        goal_model=goal_model or PaperAccountGoalModel(),
    )
    output_path.write_text(
        render_portfolio_paper_account_report(report),
        encoding="utf-8",
    )
    return report


def build_paper_account_report(
    *,
    replay: ReplayResult,
    strategy: str,
    requested_start: date,
    requested_end: date,
    run_id: str,
    output_path: Path | None = None,
    goal_model: PaperAccountGoalModel | None = None,
) -> PaperAccountReport:
    """Build a paper-account report from an already executed replay."""

    selected_goal_model = goal_model or PaperAccountGoalModel()
    return PaperAccountReport(
        run_id=run_id,
        symbol=replay.symbol,
        name=replay.name,
        strategy=strategy,
        requested_start=requested_start,
        requested_end=requested_end,
        initial_cash=replay.initial_cash,
        final_value=replay.final_value,
        total_return_pct=replay.total_return * 100,
        max_drawdown_pct=replay.max_drawdown * 100,
        bars_count=replay.bars_count,
        fund_flows_count=replay.fund_flows_count,
        missing_fund_flow_dates=len(replay.missing_fund_flow_dates),
        goal_model=selected_goal_model,
        monthly_rows=monthly_paper_account_rows(replay, goal_model=selected_goal_model),
        fills=tuple(replay.fills),
        output_path=output_path,
    )


def build_portfolio_paper_account_report(
    *,
    replays: tuple[ReplayResult, ...],
    strategy: str,
    requested_start: date,
    requested_end: date,
    initial_cash: float,
    config: PortfolioPaperAccountConfig,
    run_id: str,
    errors: tuple[str, ...] = (),
    output_path: Path | None = None,
    goal_model: PaperAccountGoalModel | None = None,
) -> PortfolioPaperAccountReport:
    """Build a shared-cash paper account from single-symbol replays."""

    if not replays:
        raise ValueError("replays must not be empty")
    _validate_portfolio_config(config)
    selected_goal_model = goal_model or PaperAccountGoalModel()
    snapshots, fills, skipped_orders = _simulate_portfolio_account(
        replays=replays,
        initial_cash=initial_cash,
        config=config,
    )
    final_value = snapshots[-1].total_value
    return PortfolioPaperAccountReport(
        run_id=run_id,
        symbols=tuple(replay.symbol for replay in replays),
        strategy=strategy,
        requested_start=requested_start,
        requested_end=requested_end,
        initial_cash=initial_cash,
        final_value=final_value,
        total_return_pct=_pct_change(initial_cash, final_value),
        max_drawdown_pct=_max_drawdown_pct(
            [snapshot.total_value for snapshot in snapshots]
        ),
        config=config,
        goal_model=selected_goal_model,
        monthly_rows=monthly_rows_from_snapshots(
            snapshots=tuple(snapshots),
            fills=tuple(fills),
            initial_cash=initial_cash,
            goal_model=selected_goal_model,
        ),
        fills=tuple(fills),
        skipped_orders=tuple(skipped_orders),
        replay_summaries=tuple(
            PortfolioReplaySummary(
                symbol=replay.symbol,
                name=replay.name,
                bars_count=replay.bars_count,
                fund_flows_count=replay.fund_flows_count,
                missing_fund_flow_dates=len(replay.missing_fund_flow_dates),
                source_fills=len(replay.fills),
            )
            for replay in replays
        ),
        errors=errors,
        output_path=output_path,
    )


def monthly_paper_account_rows(
    replay: ReplayResult,
    goal_model: PaperAccountGoalModel | None = None,
) -> tuple[MonthlyPaperAccountRow, ...]:
    """Return month-end account returns from a replay equity curve."""

    return monthly_rows_from_snapshots(
        snapshots=tuple(replay.equity_curve),
        fills=tuple(replay.fills),
        initial_cash=replay.initial_cash,
        goal_model=goal_model or PaperAccountGoalModel(),
    )


def monthly_rows_from_snapshots(
    *,
    snapshots: tuple[PortfolioSnapshot, ...],
    fills: tuple[Fill, ...],
    initial_cash: float,
    goal_model: PaperAccountGoalModel | None = None,
) -> tuple[MonthlyPaperAccountRow, ...]:
    """Return month-end account rows from arbitrary portfolio snapshots."""

    selected_goal_model = goal_model or PaperAccountGoalModel()
    sorted_snapshots = sorted(snapshots, key=lambda item: item.trade_date)
    if not sorted_snapshots:
        raise ValueError("snapshots must not be empty")

    snapshots_by_month: dict[str, list[PortfolioSnapshot]] = defaultdict(list)
    for snapshot in sorted_snapshots:
        snapshots_by_month[_month_key(snapshot.trade_date)].append(snapshot)

    fills_by_month: dict[str, list[Fill]] = defaultdict(list)
    for fill in fills:
        fills_by_month[_month_key(fill.trade_date)].append(fill)

    rows: list[MonthlyPaperAccountRow] = []
    start_value = initial_cash
    for month in sorted(snapshots_by_month):
        month_snapshots = snapshots_by_month[month]
        end_value = month_snapshots[-1].total_value
        fills = fills_by_month.get(month, [])
        avg_capital_utilization_pct = _average_capital_utilization_pct(
            month_snapshots
        )
        return_pct = _pct_change(start_value, end_value)
        rows.append(
            MonthlyPaperAccountRow(
                month=month,
                first_trade_date=month_snapshots[0].trade_date,
                last_trade_date=month_snapshots[-1].trade_date,
                start_value=start_value,
                end_value=end_value,
                return_pct=return_pct,
                buy_fills=sum(1 for fill in fills if fill.side == OrderSide.BUY),
                sell_fills=sum(1 for fill in fills if fill.side == OrderSide.SELL),
                holding_days=sum(
                    1 for snapshot in month_snapshots if snapshot.market_value > 0
                ),
                cash_days=sum(
                    1 for snapshot in month_snapshots if snapshot.market_value <= 0
                ),
                avg_capital_utilization_pct=avg_capital_utilization_pct,
                target_gap_pct=return_pct - selected_goal_model.monthly_target_return_pct,
                max_drawdown_pct=_max_drawdown_pct(
                    [snapshot.total_value for snapshot in month_snapshots]
                ),
            )
        )
        start_value = end_value
    return tuple(rows)


def render_paper_account_report(report: PaperAccountReport) -> str:
    """Render a paper-account report as Markdown."""

    buy_count = sum(1 for fill in report.fills if fill.side == OrderSide.BUY)
    sell_count = sum(1 for fill in report.fills if fill.side == OrderSide.SELL)
    coverage_pct = (
        report.fund_flows_count / report.bars_count * 100
        if report.bars_count
        else 0.0
    )
    total_fees = sum(fill.fees for fill in report.fills)
    avg_monthly_return = _average([row.return_pct for row in report.monthly_rows])
    avg_target_gap = (
        None
        if avg_monthly_return is None
        else avg_monthly_return - report.goal_model.monthly_target_return_pct
    )
    avg_capital_utilization = _average(
        [row.avg_capital_utilization_pct for row in report.monthly_rows]
    )
    lines = [
        f"# Paper Account Replay - {report.symbol}",
        "",
        "## Account Summary",
        f"- run_id: {report.run_id}",
        f"- symbol: {report.symbol} {report.name}",
        f"- strategy: {report.strategy}",
        (
            "- requested_period: "
            f"{report.requested_start.isoformat()} -> {report.requested_end.isoformat()}"
        ),
        f"- initial_cash: {report.initial_cash:.2f}",
        f"- final_value: {report.final_value:.2f}",
        f"- total_return_pct: {report.total_return_pct:.4f}%",
        f"- max_drawdown_pct: {report.max_drawdown_pct:.4f}%",
        (
            "- fund_flow_coverage: "
            f"{report.fund_flows_count}/{report.bars_count} ({coverage_pct:.2f}%)"
        ),
        f"- missing_fund_flow_dates: {report.missing_fund_flow_dates}",
        f"- fills: {len(report.fills)} total, {buy_count} buys, {sell_count} sells",
        "",
        "## Goal / Cost Model",
        f"- monthly_target_return_pct: {report.goal_model.monthly_target_return_pct:.2f}%",
        f"- cost_budget_pct: {report.goal_model.cost_budget_pct:.2f}% of monthly target",
        (
            "- monthly_cost_budget_return_pct: "
            f"{report.goal_model.monthly_cost_budget_return_pct:.2f}%"
        ),
        f"- execution_costs_paid: {total_fees:.2f}",
        f"- avg_monthly_return_pct: {_fmt_optional_pct(avg_monthly_return)}",
        f"- avg_monthly_target_gap_pct: {_fmt_optional_pct(avg_target_gap)}",
        f"- avg_capital_utilization_pct: {_fmt_optional_pct(avg_capital_utilization)}",
        "",
        "## Monthly Returns",
        (
            "| month | first_day | last_day | start_value | end_value | return_pct | "
            "target_gap | capital_utilization | buys | sells | holding_days | cash_days | "
            "month_max_drawdown |"
        ),
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report.monthly_rows:
        lines.append(
            "| "
            f"{row.month} | "
            f"{row.first_trade_date.isoformat()} | "
            f"{row.last_trade_date.isoformat()} | "
            f"{row.start_value:.2f} | "
            f"{row.end_value:.2f} | "
            f"{row.return_pct:.4f}% | "
            f"{row.target_gap_pct:.4f}% | "
            f"{row.avg_capital_utilization_pct:.4f}% | "
            f"{row.buy_fills} | "
            f"{row.sell_fills} | "
            f"{row.holding_days} | "
            f"{row.cash_days} | "
            f"{row.max_drawdown_pct:.4f}% |"
        )

    lines.extend(
        [
            "",
            "## Fills",
            "| date | side | quantity | price | gross_amount | reason |",
            "|---|---|---:|---:|---:|---|",
        ]
    )
    if report.fills:
        for fill in report.fills:
            lines.append(
                "| "
                f"{fill.trade_date.isoformat()} | "
                f"{fill.side.value} | "
                f"{fill.quantity} | "
                f"{fill.price:.2f} | "
                f"{fill.gross_amount:.2f} | "
                f"{fill.reason} |"
            )
    else:
        lines.append("| - | - | 0 | 0.00 | 0.00 | no fills |")
    return "\n".join(lines)


def render_portfolio_paper_account_report(
    report: PortfolioPaperAccountReport,
) -> str:
    """Render a shared-cash portfolio paper-account report as Markdown."""

    buy_count = sum(1 for fill in report.fills if fill.side == OrderSide.BUY)
    sell_count = sum(1 for fill in report.fills if fill.side == OrderSide.SELL)
    total_fees = sum(fill.fees for fill in report.fills)
    avg_monthly_return = _average([row.return_pct for row in report.monthly_rows])
    avg_target_gap = (
        None
        if avg_monthly_return is None
        else avg_monthly_return - report.goal_model.monthly_target_return_pct
    )
    avg_capital_utilization = _average(
        [row.avg_capital_utilization_pct for row in report.monthly_rows]
    )
    lines = [
        "# Portfolio Paper Account Replay",
        "",
        "## Account Summary",
        f"- run_id: {report.run_id}",
        f"- symbols: {', '.join(report.symbols)}",
        f"- strategy: {report.strategy}",
        (
            "- requested_period: "
            f"{report.requested_start.isoformat()} -> {report.requested_end.isoformat()}"
        ),
        f"- initial_cash: {report.initial_cash:.2f}",
        f"- final_value: {report.final_value:.2f}",
        f"- total_return_pct: {report.total_return_pct:.4f}%",
        f"- max_drawdown_pct: {report.max_drawdown_pct:.4f}%",
        f"- fills: {len(report.fills)} total, {buy_count} buys, {sell_count} sells",
        f"- skipped_orders: {len(report.skipped_orders)}",
        f"- errors: {len(report.errors)}",
        "",
        "## Goal / Cost Model",
        f"- monthly_target_return_pct: {report.goal_model.monthly_target_return_pct:.2f}%",
        f"- cost_budget_pct: {report.goal_model.cost_budget_pct:.2f}% of monthly target",
        (
            "- monthly_cost_budget_return_pct: "
            f"{report.goal_model.monthly_cost_budget_return_pct:.2f}%"
        ),
        f"- execution_costs_paid: {total_fees:.2f}",
        f"- avg_monthly_return_pct: {_fmt_optional_pct(avg_monthly_return)}",
        f"- avg_monthly_target_gap_pct: {_fmt_optional_pct(avg_target_gap)}",
        f"- avg_capital_utilization_pct: {_fmt_optional_pct(avg_capital_utilization)}",
        "",
        "## Portfolio Rules",
        f"- max_positions: {report.config.max_positions}",
        f"- min_buy_weight: {report.config.min_buy_weight * 100:.2f}%",
        f"- max_position_weight: {report.config.max_position_weight * 100:.2f}%",
        "",
        "## Monthly Returns",
        (
            "| month | first_day | last_day | start_value | end_value | return_pct | "
            "target_gap | capital_utilization | buys | sells | holding_days | cash_days | "
            "month_max_drawdown |"
        ),
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in report.monthly_rows:
        lines.append(
            "| "
            f"{row.month} | "
            f"{row.first_trade_date.isoformat()} | "
            f"{row.last_trade_date.isoformat()} | "
            f"{row.start_value:.2f} | "
            f"{row.end_value:.2f} | "
            f"{row.return_pct:.4f}% | "
            f"{row.target_gap_pct:.4f}% | "
            f"{row.avg_capital_utilization_pct:.4f}% | "
            f"{row.buy_fills} | "
            f"{row.sell_fills} | "
            f"{row.holding_days} | "
            f"{row.cash_days} | "
            f"{row.max_drawdown_pct:.4f}% |"
        )

    lines.extend(
        [
            "",
            "## Replay Coverage",
            (
                "| symbol | name | bars | fund_flows | missing_fund_flow_dates | "
                "source_fills |"
            ),
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for summary in report.replay_summaries:
        lines.append(
            "| "
            f"{summary.symbol} | "
            f"{summary.name} | "
            f"{summary.bars_count} | "
            f"{summary.fund_flows_count} | "
            f"{summary.missing_fund_flow_dates} | "
            f"{summary.source_fills} |"
        )

    lines.extend(
        [
            "",
            "## Executed Fills",
            "| date | symbol | side | quantity | price | gross_amount | reason |",
            "|---|---|---|---:|---:|---:|---|",
        ]
    )
    if report.fills:
        for fill in report.fills:
            lines.append(
                "| "
                f"{fill.trade_date.isoformat()} | "
                f"{fill.symbol} | "
                f"{fill.side.value} | "
                f"{fill.quantity} | "
                f"{fill.price:.2f} | "
                f"{fill.gross_amount:.2f} | "
                f"{fill.reason} |"
            )
    else:
        lines.append("| - | - | - | 0 | 0.00 | 0.00 | no fills |")

    lines.extend(
        [
            "",
            "## Skipped Orders",
            "| reason |",
            "|---|",
        ]
    )
    if report.skipped_orders:
        for item in report.skipped_orders[:80]:
            lines.append(f"| {item} |")
    else:
        lines.append("| none |")

    if report.errors:
        lines.extend(["", "## Data Errors", "| error |", "|---|"])
        for error in report.errors[:80]:
            lines.append(f"| {error} |")
    return "\n".join(lines)


def _simulate_portfolio_account(
    *,
    replays: tuple[ReplayResult, ...],
    initial_cash: float,
    config: PortfolioPaperAccountConfig,
) -> tuple[list[PortfolioSnapshot], list[Fill], list[str]]:
    broker = PaperBroker(initial_cash)
    latest_prices: dict[str, float] = {}
    fills: list[Fill] = []
    skipped_orders: list[str] = []
    bars_by_date: dict[date, list[Bar]] = defaultdict(list)
    source_fills_by_date: dict[date, list[Fill]] = defaultdict(list)
    source_initial_cash = {replay.symbol: replay.initial_cash for replay in replays}

    for replay in replays:
        for bar in replay.bars:
            bars_by_date[bar.trade_date].append(bar)
        for fill in replay.fills:
            source_fills_by_date[fill.trade_date].append(fill)

    all_dates = sorted(set(bars_by_date) | set(source_fills_by_date))
    if not all_dates:
        raise ValueError("replays must contain bars or fills")

    snapshots: list[PortfolioSnapshot] = []
    for trade_date in all_dates:
        for bar in bars_by_date.get(trade_date, []):
            latest_prices.setdefault(bar.symbol, bar.open)

        daily_fills = sorted(
            source_fills_by_date.get(trade_date, []),
            key=lambda fill: 0 if fill.side == OrderSide.SELL else 1,
        )
        for source_fill in daily_fills:
            latest_prices[source_fill.symbol] = source_fill.price
            if source_fill.side == OrderSide.SELL:
                executed = _execute_portfolio_sell(
                    broker=broker,
                    source_fill=source_fill,
                    latest_prices=latest_prices,
                    skipped_orders=skipped_orders,
                )
            else:
                executed = _execute_portfolio_buy(
                    broker=broker,
                    source_fill=source_fill,
                    source_initial_cash=source_initial_cash,
                    latest_prices=latest_prices,
                    config=config,
                    skipped_orders=skipped_orders,
                )
            if executed is not None:
                fills.append(executed)

        for bar in bars_by_date.get(trade_date, []):
            latest_prices[bar.symbol] = bar.close
        snapshots.append(broker.snapshot(trade_date, latest_prices))
    return snapshots, fills, skipped_orders


def _execute_portfolio_buy(
    *,
    broker: PaperBroker,
    source_fill: Fill,
    source_initial_cash: dict[str, float],
    latest_prices: dict[str, float],
    config: PortfolioPaperAccountConfig,
    skipped_orders: list[str],
) -> Fill | None:
    symbol = source_fill.symbol
    if symbol in broker.positions:
        skipped_orders.append(
            f"{source_fill.trade_date} {symbol} buy skipped: already holding"
        )
        return None
    if len(broker.positions) >= config.max_positions:
        skipped_orders.append(
            f"{source_fill.trade_date} {symbol} buy skipped: max_positions"
        )
        return None

    symbol_initial_cash = source_initial_cash.get(symbol, broker.cash)
    source_weight = (
        source_fill.gross_amount / symbol_initial_cash
        if symbol_initial_cash > 0
        else config.min_buy_weight
    )
    target_weight = min(
        max(source_weight, config.min_buy_weight),
        config.max_position_weight,
    )
    equity = broker.equity(latest_prices)
    target_value = min(equity * target_weight, broker.cash)
    quantity = _lot_quantity(target_value, source_fill.price)
    if quantity <= 0:
        skipped_orders.append(
            f"{source_fill.trade_date} {symbol} buy skipped: insufficient cash"
        )
        return None

    order = Order(
        symbol=symbol,
        side=OrderSide.BUY,
        quantity=quantity,
        requested_price=source_fill.price,
        reason=f"portfolio_entry: {source_fill.reason}",
    )
    try:
        return broker.execute_market_order(
            order,
            source_fill.price,
            source_fill.trade_date,
        )
    except ValueError as exc:
        skipped_orders.append(f"{source_fill.trade_date} {symbol} buy skipped: {exc}")
        return None


def _execute_portfolio_sell(
    *,
    broker: PaperBroker,
    source_fill: Fill,
    latest_prices: dict[str, float],
    skipped_orders: list[str],
) -> Fill | None:
    position = broker.positions.get(source_fill.symbol)
    if position is None or position.quantity <= 0:
        skipped_orders.append(
            f"{source_fill.trade_date} {source_fill.symbol} sell skipped: no position"
        )
        return None

    latest_prices[source_fill.symbol] = source_fill.price
    order = Order(
        symbol=source_fill.symbol,
        side=OrderSide.SELL,
        quantity=position.quantity,
        requested_price=source_fill.price,
        reason=f"portfolio_exit: {source_fill.reason}",
    )
    try:
        return broker.execute_market_order(
            order,
            source_fill.price,
            source_fill.trade_date,
        )
    except ValueError as exc:
        skipped_orders.append(
            f"{source_fill.trade_date} {source_fill.symbol} sell skipped: {exc}"
        )
        return None


def _lot_quantity(target_value: float, price: float) -> int:
    if target_value <= 0 or price <= 0:
        return 0
    shares = int(target_value // price)
    return shares - (shares % 100)


def _validate_portfolio_config(config: PortfolioPaperAccountConfig) -> None:
    if config.max_positions <= 0:
        raise ValueError("max_positions must be positive")
    if not 0 <= config.min_buy_weight <= config.max_position_weight <= 1:
        raise ValueError(
            "weights must satisfy 0 <= min_buy_weight <= max_position_weight <= 1"
        )


def _month_key(value: date) -> str:
    return f"{value.year:04d}-{value.month:02d}"


def _pct_change(start_value: float, end_value: float) -> float:
    if start_value == 0:
        return 0.0
    return (end_value / start_value - 1) * 100


def _max_drawdown_pct(values: list[float]) -> float:
    peak = values[0] if values else 0.0
    worst = 0.0
    for value in values:
        peak = max(peak, value)
        drawdown = (peak - value) / peak * 100 if peak else 0.0
        worst = max(worst, drawdown)
    return worst


def _average_capital_utilization_pct(snapshots: list[PortfolioSnapshot]) -> float:
    if not snapshots:
        return 0.0
    utilizations = [
        snapshot.market_value / snapshot.total_value * 100
        if snapshot.total_value > 0
        else 0.0
        for snapshot in snapshots
    ]
    return sum(utilizations) / len(utilizations)


def _average(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def _fmt_optional_pct(value: float | None) -> str:
    return "-" if value is None else f"{value:.4f}%"
