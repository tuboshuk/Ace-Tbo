"""Optional efinance quote adapter."""

from __future__ import annotations

from datetime import datetime
import math
import time
from typing import Any

from wealth_lab.models import Quote


C_CODE = "\u4ee3\u7801"
C_NAME = "\u540d\u79f0"
C_STOCK_CODE = "\u80a1\u7968\u4ee3\u7801"
C_STOCK_NAME = "\u80a1\u7968\u540d\u79f0"
C_CHANGE_PCT = "\u6da8\u8dcc\u5e45"
C_LATEST = "\u6700\u65b0\u4ef7"
C_HIGH = "\u6700\u9ad8"
C_LOW = "\u6700\u4f4e"
C_TURNOVER = "\u6362\u624b\u7387"
C_VOLUME_RATIO = "\u91cf\u6bd4"
C_VOLUME = "\u6210\u4ea4\u91cf"
C_AMOUNT = "\u6210\u4ea4\u989d"
C_UPDATE_TIME = "\u66f4\u65b0\u65f6\u95f4"


class EfinanceProvider:
    """Read stock quotes through efinance when installed."""

    provider_name = "efinance"

    def fetch_spot_quotes(self, symbols: list[str] | None = None) -> list[Quote]:
        """Fetch spot quotes from efinance."""

        try:
            import efinance as ef  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("Install optional dependency: pip install efinance") from exc

        try:
            dataframe = _call_with_retries(
                lambda: ef.stock.get_latest_quote(symbols)
                if symbols
                else ef.stock.get_realtime_quotes()
            )
        except RuntimeError:
            if symbols:
                raise
            return _fetch_realtime_quotes_direct()
        rows: list[dict[str, Any]] = dataframe.to_dict("records")
        return [
            _quote_from_row(row)
            for row in rows
            if _first(row, C_CODE, C_STOCK_CODE, default=None)
        ]


def _quote_from_row(row: dict[str, Any]) -> Quote:
    timestamp = _parse_timestamp(row.get(C_UPDATE_TIME))
    return Quote(
        symbol=str(_first(row, C_CODE, C_STOCK_CODE, default="")).zfill(6),
        name=str(_first(row, C_NAME, C_STOCK_NAME, default="")),
        price=_optional_float(row.get(C_LATEST)) or 0.0,
        change_pct=_optional_float(row.get(C_CHANGE_PCT)),
        timestamp=timestamp,
        provider=EfinanceProvider.provider_name,
        amount=_optional_float(row.get(C_AMOUNT)),
        volume=_optional_int(row.get(C_VOLUME)),
        volume_ratio=_optional_float(row.get(C_VOLUME_RATIO)),
        turnover_rate=_optional_float(row.get(C_TURNOVER)),
        high_20=None,
        low_20=None,
        sector=None,
    )


def _quote_from_direct_row(row: dict[str, Any]) -> Quote:
    timestamp = _parse_eastmoney_timestamp(row.get("f124"))
    return Quote(
        symbol=str(row.get("f12", "")).zfill(6),
        name=str(row.get("f14", "")),
        price=_optional_float(row.get("f2")) or 0.0,
        change_pct=_optional_float(row.get("f3")),
        timestamp=timestamp,
        provider=f"{EfinanceProvider.provider_name}-eastmoney-direct",
        amount=_optional_float(row.get("f6")),
        volume=_optional_int(row.get("f5")),
        volume_ratio=_optional_float(row.get("f10")),
        turnover_rate=_optional_float(row.get("f8")),
        high_20=None,
        low_20=None,
        sector=None,
    )


def _fetch_realtime_quotes_direct() -> list[Quote]:
    try:
        import requests
    except ImportError as exc:
        raise RuntimeError("Install optional dependency: pip install requests") from exc

    url = "https://push2.eastmoney.com/api/qt/clist/get"
    params = {
        "po": 1,
        "np": 1,
        "fltt": 2,
        "invt": 2,
        "fid": "f3",
        "fs": "m:0+t:6,m:0+t:80,m:1+t:2,m:1+t:23,m:0+t:81+s:2048",
        "fields": "f12,f14,f2,f3,f6,f8,f10,f5,f13,f124",
    }
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://quote.eastmoney.com/",
    }
    session = requests.Session()
    session.headers.update(headers)
    first = _fetch_direct_page(session, url, params, page=1)
    total = int(first.get("total") or 0)
    rows = list(first.get("diff") or [])
    pages = math.ceil(total / 200) if total else 1
    for page in range(2, pages + 1):
        data = _fetch_direct_page(session, url, params, page=page)
        rows.extend(data.get("diff") or [])
    return [
        _quote_from_direct_row(row)
        for row in rows
        if row.get("f12") not in (None, "")
    ]


def _fetch_direct_page(
    session: Any,
    url: str,
    base_params: dict[str, Any],
    *,
    page: int,
) -> dict[str, Any]:
    params = dict(base_params, pn=page, pz=200)
    last_error: Exception | None = None
    for attempt in range(6):
        try:
            response = session.get(url, params=params, timeout=20)
            response.raise_for_status()
            payload = response.json()
            data = payload.get("data")
            if not isinstance(data, dict):
                raise RuntimeError("eastmoney direct response missing data")
            return data
        except Exception as exc:  # noqa: BLE001 - provider exceptions vary.
            last_error = exc
            if attempt < 5:
                time.sleep(0.8 * (attempt + 1))
    raise RuntimeError(
        f"eastmoney direct quote request failed on page {page}"
    ) from last_error


def _parse_timestamp(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value
    if value in (None, ""):
        return datetime.now()
    return datetime.fromisoformat(str(value))


def _parse_eastmoney_timestamp(value: Any) -> datetime:
    if isinstance(value, (int, float)) and value > 0:
        return datetime.fromtimestamp(value)
    return datetime.now()


def _optional_float(value: Any) -> float | None:
    if value in (None, "", "-"):
        return None
    return float(value)


def _optional_int(value: Any) -> int | None:
    if value in (None, "", "-"):
        return None
    return int(value)


def _first(row: dict[str, Any], *keys: str, default: Any = 0) -> Any:
    for key in keys:
        if key in row and row[key] not in (None, ""):
            return row[key]
    return default


def _call_with_retries(callable_obj, attempts: int = 3, delay_seconds: float = 1.5):
    last_error: Exception | None = None
    for attempt in range(attempts):
        try:
            return callable_obj()
        except Exception as exc:  # noqa: BLE001 - provider exceptions vary.
            last_error = exc
            if attempt < attempts - 1:
                time.sleep(delay_seconds * (attempt + 1))
    raise RuntimeError(f"efinance quote request failed after {attempts} attempts") from last_error
