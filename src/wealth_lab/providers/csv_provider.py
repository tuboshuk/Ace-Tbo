"""CSV data provider."""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path

from wealth_lab.models import Bar


def load_bars(path: str | Path, symbols: set[str] | None = None) -> list[Bar]:
    """Load OHLCV bars from a CSV file."""

    csv_path = Path(path)
    bars: list[Bar] = []
    with csv_path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            symbol = row["symbol"].strip()
            if symbols is not None and symbol not in symbols:
                continue
            bars.append(
                Bar(
                    symbol=symbol,
                    trade_date=date.fromisoformat(row["date"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=int(row["volume"]),
                )
            )
    return sorted(bars, key=lambda item: (item.trade_date, item.symbol))

