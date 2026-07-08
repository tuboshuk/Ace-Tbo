"""Quote collectors for demo CSV and optional realtime providers."""

from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

from wealth_lab.models import Quote
from wealth_lab.providers.akshare_provider import AkshareProvider
from wealth_lab.providers.efinance_provider import EfinanceProvider


def load_quotes_from_csv(path: str | Path) -> list[Quote]:
    """Load quote snapshots from CSV."""

    csv_path = Path(path)
    quotes: list[Quote] = []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            quotes.append(
                Quote(
                    symbol=row["symbol"],
                    name=row["name"],
                    price=float(row["price"]),
                    change_pct=_optional_float(row.get("change_pct")),
                    timestamp=datetime.fromisoformat(row["timestamp"]),
                    provider=row.get("provider", "csv"),
                    amount=_optional_float(row.get("amount")),
                    volume=_optional_int(row.get("volume")),
                    volume_ratio=_optional_float(row.get("volume_ratio")),
                    turnover_rate=_optional_float(row.get("turnover_rate")),
                    high_20=_optional_float(row.get("high_20")),
                    low_20=_optional_float(row.get("low_20")),
                    sector=row.get("sector") or None,
                )
            )
    return quotes


class QuoteCollector:
    """Facade for realtime quote providers."""

    def __init__(self, provider: str = "akshare") -> None:
        if provider == "akshare":
            self._provider = AkshareProvider()
        elif provider == "efinance":
            self._provider = EfinanceProvider()
        else:
            raise ValueError(f"unsupported quote provider: {provider}")

    def fetch_spot_quotes(self) -> list[Quote]:
        """Fetch all provider spot quotes."""

        return self._provider.fetch_spot_quotes()


def _optional_float(value: str | None) -> float | None:
    if value in (None, ""):
        return None
    return float(value)


def _optional_int(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    return int(value)

