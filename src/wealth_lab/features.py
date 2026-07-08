"""Feature construction for replay and live monitoring."""

from __future__ import annotations

from datetime import datetime, time
from statistics import fmean

from wealth_lab.models import Bar, FundFlowSnapshot, Quote


def build_quote_from_bar(
    bar: Bar,
    name: str,
    previous_bars: list[Bar],
    fund_flow: FundFlowSnapshot | None = None,
    provider: str = "feature",
) -> Quote:
    """Build a quote-like snapshot from one daily bar without future leakage."""

    high_20 = max((item.high for item in previous_bars[-20:]), default=None)
    low_20 = min((item.low for item in previous_bars[-20:]), default=None)
    volume_ratio = _volume_ratio(bar, previous_bars)
    timestamp = datetime.combine(bar.trade_date, time(hour=15))
    return Quote(
        symbol=bar.symbol,
        name=name,
        price=bar.close,
        change_pct=_coalesce(fund_flow.change_pct if fund_flow else None, bar.change_pct),
        timestamp=timestamp,
        provider=provider,
        amount=bar.amount,
        volume=bar.volume,
        volume_ratio=volume_ratio,
        turnover_rate=_coalesce(
            fund_flow.turnover_rate if fund_flow else None,
            bar.turnover_rate,
        ),
        high_20=high_20,
        low_20=low_20,
        sector=None,
    )


def merge_latest_quote_features(
    quote: Quote,
    previous_bars: list[Bar],
) -> Quote:
    """Return a quote enriched with previous-window high/low data."""

    high_20 = max((item.high for item in previous_bars[-20:]), default=quote.high_20)
    low_20 = min((item.low for item in previous_bars[-20:]), default=quote.low_20)
    return Quote(
        symbol=quote.symbol,
        name=quote.name,
        price=quote.price,
        change_pct=quote.change_pct,
        timestamp=quote.timestamp,
        provider=quote.provider,
        amount=quote.amount,
        volume=quote.volume,
        volume_ratio=quote.volume_ratio,
        turnover_rate=quote.turnover_rate,
        high_20=high_20,
        low_20=low_20,
        sector=quote.sector,
    )


def _volume_ratio(bar: Bar, previous_bars: list[Bar], window: int = 20) -> float | None:
    samples = previous_bars[-window:]
    if not samples:
        return None
    average_volume = fmean(item.volume for item in samples)
    if average_volume <= 0:
        return None
    return bar.volume / average_volume


def _coalesce(first: float | None, second: float | None) -> float | None:
    return first if first is not None else second

