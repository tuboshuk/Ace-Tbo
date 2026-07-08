"""Realtime-monitor orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from wealth_lab.alert import build_alert_messages
from wealth_lab.dashboard import render_monitor_dashboard
from wealth_lab.fund_collector import load_fund_flows_from_csv
from wealth_lab.models import FundFlowSnapshot, Quote, SectorFundFlowSnapshot, StockSignal
from wealth_lab.quote_collector import load_quotes_from_csv
from wealth_lab.sector_collector import load_sector_fund_flows_from_csv
from wealth_lab.signal_engine import FundSignalEngine
from wealth_lab.storage import SQLiteRepository


@dataclass(frozen=True)
class MonitorResult:
    """Result of one monitor cycle."""

    signals: list[StockSignal]
    sectors: list[SectorFundFlowSnapshot]
    dashboard_text: str
    alert_messages: list[str]


def run_demo_monitor(
    quote_csv: Path,
    fund_flow_csv: Path,
    sector_flow_csv: Path,
    db_path: Path,
    limit: int = 10,
    persist: bool = True,
) -> MonitorResult:
    """Run one offline demo monitor cycle."""

    quotes = load_quotes_from_csv(quote_csv)
    fund_flows = load_fund_flows_from_csv(fund_flow_csv)
    sectors = load_sector_fund_flows_from_csv(sector_flow_csv)
    signals = evaluate_monitor_cycle(quotes, fund_flows, sectors)
    dashboard_text = render_monitor_dashboard(signals, sectors, limit=limit)
    alerts = build_alert_messages(signals)

    if persist:
        repository = SQLiteRepository(db_path)
        repository.upsert_quotes(quotes)
        repository.upsert_fund_flows(fund_flows)
        repository.upsert_sector_fund_flows(sectors)
        repository.upsert_stock_signals(signals)

    return MonitorResult(
        signals=signals,
        sectors=sectors,
        dashboard_text=dashboard_text,
        alert_messages=alerts,
    )


def evaluate_monitor_cycle(
    quotes: list[Quote],
    fund_flows: list[FundFlowSnapshot],
    sectors: list[SectorFundFlowSnapshot],
) -> list[StockSignal]:
    """Evaluate one monitor cycle from normalized snapshots."""

    engine = FundSignalEngine()
    quotes_by_symbol = {quote.symbol: quote for quote in quotes}
    sectors_by_name = {sector.name: sector for sector in sectors}
    signals: list[StockSignal] = []
    for fund_flow in fund_flows:
        quote = quotes_by_symbol.get(fund_flow.symbol)
        sector = sectors_by_name.get(quote.sector) if quote and quote.sector else None
        signals.append(
            engine.evaluate(
                fund_flow=fund_flow,
                quote=quote,
                sector_flow=sector,
            )
        )
    return sorted(signals, key=lambda item: item.score, reverse=True)
