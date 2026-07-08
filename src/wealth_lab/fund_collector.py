"""Fund-flow collectors for demo CSV, efinance, and AKShare."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
import time
from typing import Any

from wealth_lab.models import FundFlowSnapshot


C_STOCK_NAME = "\u80a1\u7968\u540d\u79f0"
C_STOCK_CODE = "\u80a1\u7968\u4ee3\u7801"
C_CODE = "\u4ee3\u7801"
C_NAME = "\u540d\u79f0"
C_TIME = "\u65f6\u95f4"
C_DATE = "\u65e5\u671f"
C_SUPER = "\u8d85\u5927\u5355\u51c0\u6d41\u5165"
C_LARGE = "\u5927\u5355\u51c0\u6d41\u5165"
C_MEDIUM = "\u4e2d\u5355\u51c0\u6d41\u5165"
C_SMALL = "\u5c0f\u5355\u51c0\u6d41\u5165"
C_MAIN_PCT = "\u4e3b\u529b\u51c0\u6d41\u5165\u5360\u6bd4"
C_MAIN_PCT_ALT = "\u4e3b\u529b\u51c0\u6d41\u5165-\u51c0\u5360\u6bd4"
C_CHANGE_PCT = "\u6da8\u8dcc\u5e45"
C_AMOUNT = "\u6210\u4ea4\u989d"
C_TURNOVER = "\u6362\u624b\u7387"
C_PERIOD = "\u5468\u671f"


def load_fund_flows_from_csv(path: str | Path) -> list[FundFlowSnapshot]:
    """Load fund-flow snapshots from CSV."""

    csv_path = Path(path)
    snapshots: list[FundFlowSnapshot] = []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            snapshots.append(_fund_flow_from_mapping(row, provider=row.get("provider", "csv")))
    return snapshots


class EfinanceFundCollector:
    """Collect today's minute-level and historical fund flow through efinance."""

    provider_name = "efinance"

    def fetch_today(self, symbol: str) -> list[FundFlowSnapshot]:
        """Fetch today's bill-flow rows for one symbol."""

        try:
            import efinance as ef  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("Install optional dependency: pip install efinance") from exc

        dataframe = _call_with_retries(lambda: ef.stock.get_today_bill(symbol))
        rows: list[dict[str, Any]] = dataframe.to_dict("records")
        return [
            _fund_flow_from_mapping(
                row,
                provider=self.provider_name,
                fallback_symbol=symbol,
                fallback_period="minute",
            )
            for row in rows
        ]

    def fetch_history(self, symbol: str) -> list[FundFlowSnapshot]:
        """Fetch historical daily fund-flow rows for one symbol."""

        try:
            import efinance as ef  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("Install optional dependency: pip install efinance") from exc

        dataframe = _call_with_retries(lambda: ef.stock.get_history_bill(symbol))
        rows: list[dict[str, Any]] = dataframe.to_dict("records")
        return [
            _fund_flow_from_mapping(
                row,
                provider=self.provider_name,
                fallback_symbol=symbol,
                fallback_period="daily",
            )
            for row in rows
        ]


class AkshareFundCollector:
    """Collect individual fund-flow rows through AKShare."""

    provider_name = "akshare"

    def fetch_recent(self, symbol: str, market: str | None = None) -> list[FundFlowSnapshot]:
        """Fetch recent daily fund-flow rows for one symbol."""

        try:
            import akshare as ak  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("Install optional dependency: pip install akshare") from exc

        dataframe = ak.stock_individual_fund_flow(
            stock=symbol,
            market=market or _infer_akshare_market(symbol),
        )
        rows: list[dict[str, Any]] = dataframe.to_dict("records")
        return [
            _fund_flow_from_mapping(
                row,
                provider=self.provider_name,
                fallback_symbol=symbol,
                fallback_period="daily",
            )
            for row in rows
        ]


def _fund_flow_from_mapping(
    row: dict[str, Any],
    provider: str,
    fallback_symbol: str | None = None,
    fallback_period: str = "today",
) -> FundFlowSnapshot:
    timestamp_value = _first(row, "timestamp", C_TIME, C_DATE)
    return FundFlowSnapshot(
        symbol=str(_first(row, "symbol", C_STOCK_CODE, C_CODE, default=fallback_symbol or "")).zfill(6),
        name=str(_first(row, "name", C_STOCK_NAME, C_NAME, default="")),
        timestamp=_parse_timestamp(timestamp_value),
        super_large_net_inflow=_to_money(
            _first(row, "super_large_net_inflow", C_SUPER, f"{C_SUPER}-\u51c0\u989d")
        ),
        large_net_inflow=_to_money(
            _first(row, "large_net_inflow", C_LARGE, f"{C_LARGE}-\u51c0\u989d")
        ),
        medium_net_inflow=_to_money(
            _first(row, "medium_net_inflow", C_MEDIUM, f"{C_MEDIUM}-\u51c0\u989d")
        ),
        small_net_inflow=_to_money(
            _first(row, "small_net_inflow", C_SMALL, f"{C_SMALL}-\u51c0\u989d")
        ),
        main_net_inflow_pct=_to_optional_float(
            _first(row, "main_net_inflow_pct", C_MAIN_PCT, C_MAIN_PCT_ALT, default=None)
        ),
        change_pct=_to_optional_float(_first(row, "change_pct", C_CHANGE_PCT, default=None)),
        amount=_to_optional_money(_first(row, "amount", C_AMOUNT, default=None)),
        turnover_rate=_to_optional_float(_first(row, "turnover_rate", C_TURNOVER, default=None)),
        provider=provider,
        period=str(_first(row, "period", C_PERIOD, default=fallback_period)),
    )


def _infer_akshare_market(symbol: str) -> str:
    code = symbol.strip()
    if code.startswith(("6", "9")):
        return "sh"
    if code.startswith(("0", "2", "3")):
        return "sz"
    return "bj"


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


def _to_optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(str(value).replace("%", "").replace(",", ""))


def _to_optional_money(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return _to_money(value)


def _to_money(value: Any) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).replace(",", "").strip()
    multiplier = 1.0
    if text.endswith("\u4ebf"):
        multiplier = 100000000.0
        text = text[:-1]
    elif text.endswith("\u4e07"):
        multiplier = 10000.0
        text = text[:-1]
    return float(text) * multiplier


def _call_with_retries(callable_obj, attempts: int = 3, delay_seconds: float = 1.5):
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return callable_obj()
        except Exception as exc:  # noqa: BLE001 - provider exceptions vary.
            last_error = exc
            if attempt < attempts - 1:
                time.sleep(delay_seconds * (attempt + 1))
    raise RuntimeError(f"efinance fund-flow request failed after {attempts} attempts") from last_error
