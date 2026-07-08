"""Historical volume-price replay nodes for post-trade diagnosis."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from statistics import fmean
from typing import TYPE_CHECKING

from wealth_lab.models import Bar, StockSignal

if TYPE_CHECKING:
    from wealth_lab.replay import ReplayResult


@dataclass(frozen=True)
class VolumePriceNode:
    """One historical price-volume node built without future bars."""

    trade_date: date
    close: float
    change_pct: float | None
    volume_ratio: float | None
    node_type: str
    volume_state: str
    price_position: str
    range_position_pct: float | None
    main_flow: float | None
    main_pct: float | None
    interpretation: str


@dataclass(frozen=True)
class VolumePriceReplay:
    """Volume-price node replay for a historical result."""

    nodes: tuple[VolumePriceNode, ...]
    expansion_nodes: int
    shrink_nodes: int
    constructive_nodes: int
    risk_nodes: int
    latest_node: VolumePriceNode | None


def build_volume_price_replay(
    result: ReplayResult,
    *,
    window: int = 20,
) -> VolumePriceReplay:
    """Build a historical volume-price replay from all available bars."""

    if window <= 0:
        raise ValueError("window must be positive")
    bars = result.bars
    if not bars:
        bars = _bars_from_signals(result.signals)
    signals_by_date = {
        signal.timestamp.date(): signal
        for signal in result.signals
    }
    nodes = tuple(
        build_volume_price_node(
            bar=bar,
            previous_bars=bars[max(0, index - window):index],
            signal=signals_by_date.get(bar.trade_date),
        )
        for index, bar in enumerate(bars)
        if index > 0
    )
    return VolumePriceReplay(
        nodes=nodes,
        expansion_nodes=sum(node.volume_state == "expansion" for node in nodes),
        shrink_nodes=sum(node.volume_state == "shrink" for node in nodes),
        constructive_nodes=sum(
            node.node_type
            in {
                "volume_breakout",
                "shrink_pullback",
                "dry_up_base",
                "quiet_consolidation",
            }
            for node in nodes
        ),
        risk_nodes=sum(
            node.node_type
            in {
                "high_volume_failed_breakout",
                "climax_volume_up",
                "volume_selloff",
                "breakdown_on_volume",
            }
            for node in nodes
        ),
        latest_node=nodes[-1] if nodes else None,
    )


def build_volume_price_node(
    *,
    bar: Bar,
    previous_bars: list[Bar],
    signal: StockSignal | None,
) -> VolumePriceNode:
    volume_ratio = _volume_ratio(bar, previous_bars)
    previous_high = max((item.high for item in previous_bars), default=None)
    previous_low = min((item.low for item in previous_bars), default=None)
    range_position = _range_position(bar.close, previous_low, previous_high)
    volume_state = _volume_state(volume_ratio)
    price_position = _price_position(
        close=bar.close,
        high=bar.high,
        previous_low=previous_low,
        previous_high=previous_high,
        range_position=range_position,
    )
    node_type, interpretation = _classify_node(
        bar=bar,
        volume_ratio=volume_ratio,
        volume_state=volume_state,
        price_position=price_position,
        range_position=range_position,
        previous_high=previous_high,
        previous_low=previous_low,
    )
    main_flow = signal.fund_flow.main_net_inflow if signal is not None else None
    main_pct = signal.fund_flow.main_net_inflow_pct if signal is not None else None
    return VolumePriceNode(
        trade_date=bar.trade_date,
        close=bar.close,
        change_pct=bar.change_pct,
        volume_ratio=volume_ratio,
        node_type=node_type,
        volume_state=volume_state,
        price_position=price_position,
        range_position_pct=None if range_position is None else range_position * 100,
        main_flow=main_flow,
        main_pct=main_pct,
        interpretation=interpretation,
    )


def _classify_node(
    *,
    bar: Bar,
    volume_ratio: float | None,
    volume_state: str,
    price_position: str,
    range_position: float | None,
    previous_high: float | None,
    previous_low: float | None,
) -> tuple[str, str]:
    change_pct = bar.change_pct or 0.0
    broke_high = bool(previous_high is not None and bar.close >= previous_high)
    tested_high_failed = bool(
        previous_high is not None
        and bar.high >= previous_high
        and bar.close < previous_high
    )
    broke_low = bool(previous_low is not None and bar.close <= previous_low)
    expanded = volume_state == "expansion"
    shrank = volume_state == "shrink"

    if expanded and broke_high and change_pct > 0:
        return "volume_breakout", "price broke prior range with expanded volume"
    if expanded and tested_high_failed:
        return "high_volume_failed_breakout", "expanded volume tested high but closed back below"
    if expanded and broke_low:
        return "breakdown_on_volume", "price broke prior low on expanded volume"
    if expanded and change_pct <= -3.0:
        return "volume_selloff", "expanded volume with weak price"
    if expanded and change_pct >= 7.0 and price_position == "near_high":
        return "climax_volume_up", "large up move near high; watch chase risk"
    if shrank and change_pct <= 0 and price_position in {"middle", "near_high"}:
        return "shrink_pullback", "pullback happened on shrinking volume"
    if shrank and abs(change_pct) <= 2.0 and price_position == "near_low":
        return "dry_up_base", "volume dried near the lower range"
    if shrank and abs(change_pct) <= 2.0:
        return "quiet_consolidation", "small price movement with shrinking volume"
    if range_position is not None:
        return "normal", "no special volume-price node"
    return "insufficient_history", "not enough prior bars for range context"


def _volume_ratio(bar: Bar, previous_bars: list[Bar]) -> float | None:
    if not previous_bars:
        return None
    average_volume = fmean(item.volume for item in previous_bars)
    if average_volume <= 0:
        return None
    return bar.volume / average_volume


def _volume_state(volume_ratio: float | None) -> str:
    if volume_ratio is None:
        return "unknown"
    if volume_ratio >= 1.8:
        return "expansion"
    if volume_ratio <= 0.75:
        return "shrink"
    return "normal"


def _range_position(
    close: float,
    previous_low: float | None,
    previous_high: float | None,
) -> float | None:
    if previous_low is None or previous_high is None or previous_high <= previous_low:
        return None
    return (close - previous_low) / (previous_high - previous_low)


def _price_position(
    *,
    close: float,
    high: float,
    previous_low: float | None,
    previous_high: float | None,
    range_position: float | None,
) -> str:
    if previous_high is not None and close >= previous_high:
        return "breakout"
    if previous_high is not None and high >= previous_high and close < previous_high:
        return "failed_high_test"
    if previous_low is not None and close <= previous_low:
        return "breakdown"
    if range_position is None:
        return "unknown"
    if range_position >= 0.75:
        return "near_high"
    if range_position <= 0.30:
        return "near_low"
    return "middle"


def _bars_from_signals(signals: list[StockSignal]) -> list[Bar]:
    bars: list[Bar] = []
    for signal in signals:
        quote = signal.quote
        if quote is None:
            continue
        bars.append(
            Bar(
                symbol=signal.symbol,
                trade_date=signal.timestamp.date(),
                open=quote.price,
                high=quote.price,
                low=quote.price,
                close=quote.price,
                volume=quote.volume or 0,
                amount=quote.amount,
                change_pct=quote.change_pct,
                turnover_rate=quote.turnover_rate,
            )
        )
    return bars
