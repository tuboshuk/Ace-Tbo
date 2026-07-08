"""Text dashboard rendering for realtime anomaly monitoring."""

from __future__ import annotations

from collections.abc import Iterable

from wealth_lab.models import (
    AnomalyKind,
    FundSignal,
    PatternTag,
    SectorFundFlowSnapshot,
    StockSignal,
)


TITLE = "\u5b9e\u65f6\u5f02\u52a8\u76d1\u63a7\u5668"
RISK_RANK = "\u98ce\u9669\u5f02\u52a8\u699c"
TRADE_CANDIDATES = "\u53ef\u4ea4\u6613\u5019\u9009\u699c"
MAIN_BUY = "\u8d44\u91d1\u6d41\u5165\u89c2\u5bdf"
MAIN_SELL = "\u8d44\u91d1\u6d41\u51fa\u89c2\u5bdf"
SUPER_IN = "\u8d85\u5927\u5355\u6d41\u5165\u699c"
SUPER_OUT = "\u8d85\u5927\u5355\u6d41\u51fa\u699c"
DISTRIBUTION = "\u7591\u4f3c\u6d3e\u53d1/\u51fa\u8d27"
ACCUMULATION = "\u7591\u4f3c\u5438\u7b79"
WATCHLIST = "\u81ea\u9009\u80a1\u4e3b\u529b\u8d44\u91d1\u72b6\u6001"
SECTOR_RANK = "\u677f\u5757\u8d44\u91d1\u6d41\u5165\u6392\u884c"
EMPTY = "\u65e0"


def render_monitor_dashboard(
    signals: list[StockSignal],
    sectors: list[SectorFundFlowSnapshot],
    limit: int = 10,
) -> str:
    """Render a compact text dashboard."""

    ordered = sorted(signals, key=lambda item: item.score, reverse=True)
    sections = [
        (RISK_RANK, _risk_signals(ordered), "score"),
        (TRADE_CANDIDATES, _trade_candidates(ordered), "score"),
        (MAIN_BUY, _by_signal(ordered, FundSignal.BUY), "main_desc"),
        (MAIN_SELL, _by_signal(ordered, FundSignal.SELL), "main_asc"),
        (SUPER_IN, ordered, "super_desc"),
        (SUPER_OUT, ordered, "super_asc"),
        (DISTRIBUTION, _distribution_like(ordered), "score"),
        (ACCUMULATION, _accumulation_like(ordered), "score"),
        (WATCHLIST, ordered, "score"),
    ]

    lines = [f"# {TITLE}", ""]
    for title, section_signals, sort_key in sections:
        lines.extend(_render_signal_section(title, section_signals, limit, sort_key))
        lines.append("")

    lines.extend(_render_sector_section(SECTOR_RANK, sectors, limit))
    return "\n".join(lines).rstrip()


def _by_signal(
    signals: Iterable[StockSignal],
    fund_signal: FundSignal,
) -> list[StockSignal]:
    return [signal for signal in signals if signal.fund_signal == fund_signal]


def _risk_signals(signals: Iterable[StockSignal]) -> list[StockSignal]:
    return [signal for signal in signals if _is_risk_signal(signal)]


def _trade_candidates(signals: Iterable[StockSignal]) -> list[StockSignal]:
    return [
        signal
        for signal in signals
        if not _is_risk_signal(signal)
        and (
            signal.fund_signal == FundSignal.BUY
            or _is_constructive_accumulation(signal)
        )
    ]


def _is_risk_signal(signal: StockSignal) -> bool:
    tags = set(signal.pattern_tags)
    return (
        signal.fund_signal in {FundSignal.SELL, FundSignal.SUSPECTED_DISTRIBUTION}
        or bool(
            tags
            & {PatternTag.SUSPECTED_DISTRIBUTION, PatternTag.FAILED_BREAKOUT}
        )
        or _has_main_flow_out(signal)
        or _is_volume_down(signal)
    )


def _is_constructive_accumulation(signal: StockSignal) -> bool:
    return (
        (
            signal.fund_signal == FundSignal.SUSPECTED_ACCUMULATION
            or PatternTag.SUSPECTED_ACCUMULATION in signal.pattern_tags
        )
        and signal.fund_flow.main_net_inflow > 0
    )


def _has_main_flow_out(signal: StockSignal) -> bool:
    return signal.fund_flow.main_net_inflow < 0 or bool(
        signal.fund_flow.main_net_inflow_pct is not None
        and signal.fund_flow.main_net_inflow_pct < 0
    )


def _is_volume_down(signal: StockSignal) -> bool:
    change_pct = signal.fund_flow.change_pct
    if change_pct is None and signal.quote is not None:
        change_pct = signal.quote.change_pct
    if change_pct is None or change_pct >= 0:
        return False

    return (
        AnomalyKind.VOLUME_SPIKE in signal.anomalies
        or bool(
            signal.quote is not None
            and signal.quote.volume_ratio is not None
            and signal.quote.volume_ratio >= 1.5
        )
    )


def _distribution_like(signals: Iterable[StockSignal]) -> list[StockSignal]:
    return [
        signal
        for signal in signals
        if PatternTag.SUSPECTED_DISTRIBUTION in signal.pattern_tags
        or signal.fund_signal == FundSignal.SUSPECTED_DISTRIBUTION
    ]


def _accumulation_like(signals: Iterable[StockSignal]) -> list[StockSignal]:
    return [
        signal
        for signal in signals
        if PatternTag.SUSPECTED_ACCUMULATION in signal.pattern_tags
        or signal.fund_signal == FundSignal.SUSPECTED_ACCUMULATION
    ]


def _render_signal_section(
    title: str,
    signals: list[StockSignal],
    limit: int,
    sort_key: str,
) -> list[str]:
    sorted_signals = _sort_signals(signals, sort_key)[:limit]
    lines = [f"## {title}"]
    if not sorted_signals:
        return lines + [EMPTY]

    lines.append(
        "\u4ee3\u7801 | \u540d\u79f0 | fund_signal | "
        "\u89c2\u5bdf\u6807\u7b7e | \u4e3b\u529b\u51c0\u6d41\u5165 | "
        "\u4e3b\u529b\u5360\u6bd4 | \u6da8\u8dcc\u5e45 | \u6362\u624b\u7387 | "
        "\u5f02\u52a8"
    )
    lines.append("--- | --- | --- | --- | ---: | ---: | ---: | ---: | ---")
    for signal in sorted_signals:
        flow = signal.fund_flow
        anomalies = "\u3001".join(anomaly.value for anomaly in signal.anomalies) or "-"
        pattern_tags = "\u3001".join(tag.value for tag in signal.pattern_tags) or "-"
        lines.append(
            " | ".join(
                [
                    signal.symbol,
                    signal.name,
                    signal.fund_signal.value,
                    pattern_tags,
                    _money(flow.main_net_inflow),
                    _pct(flow.main_net_inflow_pct),
                    _pct(flow.change_pct),
                    _pct(flow.turnover_rate),
                    anomalies,
                ]
            )
        )
    return lines


def _render_sector_section(
    title: str,
    sectors: list[SectorFundFlowSnapshot],
    limit: int,
) -> list[str]:
    sorted_sectors = sorted(
        sectors,
        key=lambda item: item.main_net_inflow,
        reverse=True,
    )[:limit]
    lines = [f"## {title}"]
    if not sorted_sectors:
        return lines + [EMPTY]

    lines.append(
        "\u677f\u5757 | \u7c7b\u578b | \u4e3b\u529b\u51c0\u6d41\u5165 | "
        "\u4e3b\u529b\u5360\u6bd4 | \u6da8\u8dcc\u5e45 | "
        "\u6d41\u5165\u80a1\u7968\u6570 | \u9886\u6da8\u80a1"
    )
    lines.append("--- | --- | ---: | ---: | ---: | ---: | ---")
    for sector in sorted_sectors:
        lines.append(
            " | ".join(
                [
                    sector.name,
                    sector.sector_type,
                    _money(sector.main_net_inflow),
                    _pct(sector.main_net_inflow_pct),
                    _pct(sector.change_pct),
                    str(sector.inflow_stock_count or "-"),
                    sector.leading_stock or "-",
                ]
            )
        )
    return lines


def _sort_signals(signals: list[StockSignal], sort_key: str) -> list[StockSignal]:
    if sort_key == "main_desc":
        return sorted(signals, key=lambda item: item.fund_flow.main_net_inflow, reverse=True)
    if sort_key == "main_asc":
        return sorted(signals, key=lambda item: item.fund_flow.main_net_inflow)
    if sort_key == "super_desc":
        return sorted(
            signals,
            key=lambda item: item.fund_flow.super_large_net_inflow,
            reverse=True,
        )
    if sort_key == "super_asc":
        return sorted(signals, key=lambda item: item.fund_flow.super_large_net_inflow)
    return sorted(signals, key=lambda item: item.score, reverse=True)


def _money(value: float | None) -> str:
    if value is None:
        return "-"
    abs_value = abs(value)
    if abs_value >= 100000000:
        return f"{value / 100000000:.2f}\u4ebf"
    if abs_value >= 10000:
        return f"{value / 10000:.2f}\u4e07"
    return f"{value:.2f}"


def _pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}%"
