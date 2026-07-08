"""Historical market-data providers."""

from __future__ import annotations

from datetime import date, datetime, timedelta
import time
from typing import Any

from wealth_lab.models import Bar
from wealth_lab.rules import normalize_symbol


C_STOCK_NAME = "\u80a1\u7968\u540d\u79f0"
C_STOCK_CODE = "\u80a1\u7968\u4ee3\u7801"
C_DATE = "\u65e5\u671f"
C_OPEN = "\u5f00\u76d8"
C_CLOSE = "\u6536\u76d8"
C_HIGH = "\u6700\u9ad8"
C_LOW = "\u6700\u4f4e"
C_VOLUME = "\u6210\u4ea4\u91cf"
C_AMOUNT = "\u6210\u4ea4\u989d"
C_CHANGE_PCT = "\u6da8\u8dcc\u5e45"
C_TURNOVER = "\u6362\u624b\u7387"


class EfinanceHistoricalProvider:
    """Fetch historical daily bars through efinance."""

    provider_name = "efinance"

    def fetch_daily_bars(
        self,
        symbol: str,
        start: date,
        end: date,
        adjust: int = 1,
    ) -> list[Bar]:
        """Fetch daily bars for a symbol.

        Args:
            symbol: Six-digit A-share code.
            start: Inclusive start date.
            end: Inclusive end date.
            adjust: efinance adjustment flag. 1 is forward adjusted.
        """

        try:
            import efinance as ef  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("Install optional dependency: pip install efinance") from exc

        dataframe = _call_with_retries(
            lambda: ef.stock.get_quote_history(
                normalize_symbol(symbol),
                beg=start.strftime("%Y%m%d"),
                end=end.strftime("%Y%m%d"),
                fqt=adjust,
            )
        )
        rows: list[dict[str, Any]] = dataframe.to_dict("records")
        return [_bar_from_row(row) for row in rows]

    def fetch_last_year_daily_bars(self, symbol: str, end: date | None = None) -> list[Bar]:
        """Fetch approximately one year of daily bars."""

        end_date = end or date.today()
        start_date = end_date - timedelta(days=370)
        return self.fetch_daily_bars(symbol, start_date, end_date)


class BaoStockHistoricalProvider:
    """Fetch historical daily bars through BaoStock."""

    provider_name = "baostock"

    def __init__(self, *, keep_session: bool = False) -> None:
        self._keep_session = keep_session
        self._logged_in = False

    def fetch_daily_bars(
        self,
        symbol: str,
        start: date,
        end: date,
        adjust: str = "2",
    ) -> list[Bar]:
        """Fetch daily bars for a symbol through BaoStock."""

        try:
            import baostock as bs  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("Install optional dependency: pip install baostock") from exc

        self._ensure_login(bs)
        try:
            result = bs.query_history_k_data_plus(
                _baostock_symbol(symbol),
                "date,code,open,high,low,close,volume,amount,turn,pctChg",
                start_date=start.isoformat(),
                end_date=end.isoformat(),
                frequency="d",
                adjustflag=adjust,
            )
            if result.error_code != "0":
                raise RuntimeError(f"BaoStock query failed: {result.error_msg}")
            bars: list[Bar] = []
            while result.next():
                rows = dict(zip(result.fields, result.get_row_data(), strict=True))
                try:
                    bars.append(_bar_from_baostock_row(rows))
                except ValueError:
                    continue
            return bars
        finally:
            if not self._keep_session:
                bs.logout()
                self._logged_in = False

    def close(self) -> None:
        """Close a kept BaoStock session if one is open."""

        if not self._logged_in:
            return
        try:
            import baostock as bs  # type: ignore[import-not-found]
        except ImportError:
            self._logged_in = False
            return
        bs.logout()
        self._logged_in = False

    def _ensure_login(self, baostock_module: Any) -> None:
        if self._keep_session and self._logged_in:
            return
        login_result = baostock_module.login()
        if login_result.error_code != "0":
            raise RuntimeError(f"BaoStock login failed: {login_result.error_msg}")
        self._logged_in = True


def _bar_from_row(row: dict[str, Any]) -> Bar:
    return Bar(
        symbol=str(row[C_STOCK_CODE]).zfill(6),
        trade_date=_parse_date(row[C_DATE]),
        open=float(row[C_OPEN]),
        high=float(row[C_HIGH]),
        low=float(row[C_LOW]),
        close=float(row[C_CLOSE]),
        volume=int(row[C_VOLUME]),
        amount=_optional_float(row.get(C_AMOUNT)),
        change_pct=_optional_float(row.get(C_CHANGE_PCT)),
        turnover_rate=_optional_float(row.get(C_TURNOVER)),
    )


def _bar_from_baostock_row(row: dict[str, str]) -> Bar:
    return Bar(
        symbol=normalize_symbol(row["code"]),
        trade_date=_parse_date(row["date"]),
        open=float(row["open"]),
        high=float(row["high"]),
        low=float(row["low"]),
        close=float(row["close"]),
        volume=int(float(row["volume"])),
        amount=_optional_float(row.get("amount")),
        change_pct=_optional_float(row.get("pctChg")),
        turnover_rate=_optional_float(row.get("turn")),
    )


def _baostock_symbol(symbol: str) -> str:
    code = normalize_symbol(symbol)
    if code.startswith(("6", "9")):
        return f"sh.{code}"
    return f"sz.{code}"


def _parse_date(value: Any) -> date:
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    return date.fromisoformat(str(value))


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _call_with_retries(callable_obj, attempts: int = 3, delay_seconds: float = 1.5):
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return callable_obj()
        except Exception as exc:  # noqa: BLE001 - provider exceptions vary.
            last_error = exc
            if attempt < attempts - 1:
                time.sleep(delay_seconds * (attempt + 1))
    raise RuntimeError(f"efinance historical request failed after {attempts} attempts") from last_error
