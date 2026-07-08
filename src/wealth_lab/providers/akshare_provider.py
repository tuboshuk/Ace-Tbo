"""Optional AKShare adapter."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from wealth_lab.models import Quote


class AkshareProvider:
    """Read A-share spot quotes through AKShare when installed."""

    provider_name = "akshare"

    def fetch_spot_quotes(self) -> list[Quote]:
        """Fetch沪深京 A 股 spot quotes from AKShare."""

        try:
            import akshare as ak  # type: ignore[import-not-found]
        except ImportError as exc:
            raise RuntimeError("Install optional dependency: pip install akshare") from exc

        dataframe = ak.stock_zh_a_spot_em()
        rows: list[dict[str, Any]] = dataframe.to_dict("records")
        timestamp = datetime.now()
        return [
            Quote(
                symbol=str(row.get("代码", "")).zfill(6),
                name=str(row.get("名称", "")),
                price=float(row.get("最新价") or 0),
                change_pct=_optional_float(row.get("涨跌幅")),
                timestamp=timestamp,
                provider=self.provider_name,
            )
            for row in rows
            if row.get("代码")
        ]


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    return float(value)

