"""Analysis orchestration for real-data stock replay and live watch."""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from wealth_lab.features import build_quote_from_bar, merge_latest_quote_features
from wealth_lab.fund_collector import EfinanceFundCollector
from wealth_lab.models import FundFlowSnapshot, Quote, StockSignal
from wealth_lab.monitor import MonitorResult
from wealth_lab.providers.efinance_provider import EfinanceProvider
from wealth_lab.providers.historical_provider import (
    BaoStockHistoricalProvider,
    EfinanceHistoricalProvider,
)
from wealth_lab.replay import HistoricalReplayRunner, ReplayResult
from wealth_lab.report import render_replay_report
from wealth_lab.signal_engine import FundSignalEngine, SignalThresholds
from wealth_lab.storage import SQLiteRepository
from wealth_lab.trade_discipline import DisciplineConfig, TradeDiscipline


def analyze_stock_replay(
    symbol: str,
    days: int,
    initial_cash: float,
    target_annual_return: float = 0.10,
    db_path: Path | None = None,
    persist: bool = True,
    discipline_config: DisciplineConfig | None = None,
) -> tuple[ReplayResult, str]:
    """Fetch real data, run historical replay, and render a report."""

    end = date.today()
    start = end - timedelta(days=days)
    fund_collector = EfinanceFundCollector()
    bars = _fetch_daily_bars_with_fallback(symbol, start, end)
    fund_flows = fund_collector.fetch_history(symbol)
    fund_flows = [
        item for item in fund_flows
        if start <= item.timestamp.date() <= end
    ]
    result = HistoricalReplayRunner(
        bars=bars,
        fund_flows=fund_flows,
        initial_cash=initial_cash,
        discipline=TradeDiscipline(discipline_config)
        if discipline_config is not None
        else None,
    ).run()
    current_signal = _try_fetch_current_signal(symbol)
    if persist and db_path is not None:
        repository = SQLiteRepository(db_path)
        repository.upsert_bars(bars)
        repository.upsert_fund_flows(fund_flows)
        repository.upsert_stock_signals(result.signals)
        repository.insert_fills(result.fills)
    return result, render_replay_report(
        result,
        target_annual_return=target_annual_return,
        current_signal=current_signal,
        discipline_config=discipline_config,
    )


def watch_once(
    symbols: list[str],
    db_path: Path | None = None,
    persist: bool = True,
) -> MonitorResult:
    """Run one real-data watch cycle for a small watchlist."""

    if not symbols:
        raise ValueError("symbols must not be empty")

    quote_provider = EfinanceProvider()
    fund_collector = EfinanceFundCollector()
    quotes = _fetch_quotes_with_fallback(symbols, quote_provider)
    fund_flows: list[FundFlowSnapshot] = []
    signals: list[StockSignal] = []
    engine = FundSignalEngine(SignalThresholds(require_sector_confirmation=False))

    for quote in quotes:
        bars = _fetch_daily_bars_with_fallback(
            quote.symbol,
            date.today() - timedelta(days=90),
            date.today(),
        )
        previous_bars = [
            bar for bar in bars
            if bar.trade_date < quote.timestamp.date()
        ] or bars[-20:]
        enriched_quote = merge_latest_quote_features(quote, previous_bars)
        today_flow = _latest_today_flow(fund_collector, quote)
        fund_flows.append(today_flow)
        signals.append(
            engine.evaluate(
                fund_flow=today_flow,
                quote=enriched_quote,
                sector_flow=None,
                recent_bars=previous_bars[-20:],
            )
        )

    signals = sorted(signals, key=lambda item: item.score, reverse=True)
    from wealth_lab.alert import build_alert_messages
    from wealth_lab.dashboard import render_monitor_dashboard

    dashboard = render_monitor_dashboard(signals, sectors=[], limit=len(signals))
    alerts = build_alert_messages(signals)
    if persist and db_path is not None:
        repository = SQLiteRepository(db_path)
        repository.upsert_quotes([signal.quote for signal in signals if signal.quote])
        repository.upsert_fund_flows(fund_flows)
        repository.upsert_stock_signals(signals)
    return MonitorResult(
        signals=signals,
        sectors=[],
        dashboard_text=dashboard,
        alert_messages=alerts,
    )


def _try_fetch_current_signal(symbol: str) -> StockSignal | None:
    """Fetch a current signal for proof gating without blocking replay."""

    try:
        watch = watch_once([symbol], db_path=None, persist=False)
    except Exception:  # noqa: BLE001 - live providers can fail independently.
        return None
    return watch.signals[0] if watch.signals else None


def _latest_today_flow(
    fund_collector: EfinanceFundCollector,
    quote: Quote,
) -> FundFlowSnapshot:
    period = "minute"
    try:
        flows = fund_collector.fetch_today(quote.symbol)
    except Exception:  # noqa: BLE001 - fallback to last historical fund-flow row.
        flows = fund_collector.fetch_history(quote.symbol)
        period = "daily-fallback"
    if not flows:
        flows = fund_collector.fetch_history(quote.symbol)
        period = "daily-fallback"
    if not flows:
        raise RuntimeError(f"no today fund-flow rows for {quote.symbol}")
    latest = flows[-1]
    amount = quote.amount or latest.amount
    main_pct = latest.main_net_inflow_pct
    if main_pct is None and amount and amount > 0:
        main_pct = latest.main_net_inflow / amount * 100
    return replace(
        latest,
        name=latest.name or quote.name,
        main_net_inflow_pct=main_pct,
        change_pct=latest.change_pct if latest.change_pct is not None else quote.change_pct,
        amount=amount,
        turnover_rate=latest.turnover_rate
        if latest.turnover_rate is not None
        else quote.turnover_rate,
        period=period if period == "daily-fallback" else latest.period,
    )


def _fetch_daily_bars_with_fallback(symbol: str, start: date, end: date):
    providers = [
        EfinanceHistoricalProvider(),
        BaoStockHistoricalProvider(),
    ]
    errors: list[str] = []
    for provider in providers:
        try:
            bars = provider.fetch_daily_bars(symbol, start, end)
            if bars:
                return bars
            errors.append(f"{provider.provider_name}: empty result")
        except Exception as exc:  # noqa: BLE001 - provider exceptions vary.
            errors.append(f"{provider.provider_name}: {exc}")
    raise RuntimeError("all historical bar providers failed: " + "; ".join(errors))


def _fetch_quotes_with_fallback(
    symbols: list[str],
    quote_provider: EfinanceProvider,
) -> list[Quote]:
    try:
        quotes = quote_provider.fetch_spot_quotes(symbols)
        if quotes:
            return quotes
    except Exception:
        pass

    fallback_quotes: list[Quote] = []
    for symbol in symbols:
        bars = _fetch_daily_bars_with_fallback(
            symbol,
            date.today() - timedelta(days=90),
            date.today(),
        )
        if not bars:
            continue
        latest_bar = bars[-1]
        fallback_quotes.append(
            build_quote_from_bar(
                bar=latest_bar,
                name=symbol,
                previous_bars=bars[:-1],
                fund_flow=None,
                provider="daily-fallback",
            )
        )
    return fallback_quotes
