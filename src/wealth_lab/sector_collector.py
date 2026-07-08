"""Sector fund-flow collectors for demo CSV and AKShare."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any

from wealth_lab.models import SectorFundFlowSnapshot


def load_sector_fund_flows_from_csv(path: str | Path) -> list[SectorFundFlowSnapshot]:
    """Load sector fund-flow snapshots from CSV."""

    csv_path = Path(path)
    snapshots: list[SectorFundFlowSnapshot] = []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            snapshots.append(_sector_from_mapping(row, provider=row.get("provider", "csv")))
    return snapshots


class AkshareSectorFundCollector:
    """Collect industry or concept fund-flow rankings through AKShare."""

    provider_name = "akshare"

    def fetch_rank(
        self,
        indicator: str = "今日",
        sector_type: str = "行业资金流",
    ) -> list[SectorFundFlowSnapshot]:
        """Fetch sector fund-flow rankings."""

        try:
            import akshare as ak  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("Install optional dependency: pip install akshare") from exc

        dataframe = ak.stock_sector_fund_flow_rank(
            indicator=indicator,
            sector_type=sector_type,
        )
        rows: list[dict[str, Any]] = dataframe.to_dict("records")
        return [
            _sector_from_mapping(
                row,
                provider=self.provider_name,
                fallback_sector_type=sector_type,
                fallback_period=indicator,
            )
            for row in rows
        ]


def _sector_from_mapping(
    row: dict[str, Any],
    provider: str,
    fallback_sector_type: str = "industry",
    fallback_period: str = "today",
) -> SectorFundFlowSnapshot:
    return SectorFundFlowSnapshot(
        name=str(_first(row, "name", "名称", "行业", "概念", default="")),
        sector_type=str(_first(row, "sector_type", "类型", default=fallback_sector_type)),
        timestamp=_parse_timestamp(_first(row, "timestamp", "时间", "日期", default=None)),
        super_large_net_inflow=_to_money(
            _first(row, "super_large_net_inflow", "超大单净流入", "超大单净流入-净额")
        ),
        large_net_inflow=_to_money(
            _first(row, "large_net_inflow", "大单净流入", "大单净流入-净额")
        ),
        medium_net_inflow=_to_money(
            _first(row, "medium_net_inflow", "中单净流入", "中单净流入-净额")
        ),
        small_net_inflow=_to_money(
            _first(row, "small_net_inflow", "小单净流入", "小单净流入-净额")
        ),
        main_net_inflow_pct=_optional_float(
            _first(row, "main_net_inflow_pct", "主力净流入占比", "主力净流入-净占比")
        ),
        change_pct=_optional_float(_first(row, "change_pct", "涨跌幅")),
        leading_stock=_optional_str(_first(row, "leading_stock", "领涨股", default=None)),
        inflow_stock_count=_optional_int(
            _first(row, "inflow_stock_count", "资金流入股票数量", default=None)
        ),
        provider=provider,
        period=str(_first(row, "period", "周期", default=fallback_period)),
    )


def _first(row: dict[str, Any], *keys: str, default: Any = 0) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return default


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if value in (None, ""):
        return datetime.now()
    text = str(value)
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return datetime.fromisoformat(f"{text}T15:00:00")


def _optional_str(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return str(value)


def _optional_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    return int(value)


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(str(value).replace("%", "").replace(",", ""))


def _to_money(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").strip()
    multiplier = 1.0
    if text.endswith("亿"):
        multiplier = 100000000.0
        text = text[:-1]
    elif text.endswith("万"):
        multiplier = 10000.0
        text = text[:-1]
    return float(text) * multiplier
