from datetime import datetime

from wealth_lab.dashboard import (
    RISK_RANK,
    TRADE_CANDIDATES,
    render_monitor_dashboard,
)
from wealth_lab.models import (
    FundFlowSnapshot,
    FundSignal,
    PatternTag,
    Quote,
    StockSignal,
)


def test_distribution_failed_breakout_stays_out_of_trade_candidates() -> None:
    danger = _signal(
        symbol="000001",
        fund_signal=FundSignal.SUSPECTED_DISTRIBUTION,
        pattern_tags=(PatternTag.FAILED_BREAKOUT,),
        score=100,
        main_flow=-2_000_000,
        main_pct=-8.0,
        change_pct=-3.0,
    )

    markdown = render_monitor_dashboard([danger], sectors=[])

    assert danger.symbol in _section(markdown, RISK_RANK)
    assert danger.symbol not in _section(markdown, TRADE_CANDIDATES)


def test_buy_and_accumulation_enter_trade_candidates() -> None:
    buy = _signal(
        symbol="000002",
        fund_signal=FundSignal.BUY,
        pattern_tags=(PatternTag.VOLUME_BREAKOUT,),
        score=90,
        main_flow=2_000_000,
        main_pct=8.0,
        change_pct=3.0,
    )
    accumulation = _signal(
        symbol="000003",
        fund_signal=FundSignal.SUSPECTED_ACCUMULATION,
        pattern_tags=(PatternTag.SUSPECTED_ACCUMULATION,),
        score=85,
        main_flow=1_500_000,
        main_pct=5.0,
        change_pct=0.8,
    )

    markdown = render_monitor_dashboard([buy, accumulation], sectors=[])
    candidates = _section(markdown, TRADE_CANDIDATES)

    assert buy.symbol in candidates
    assert accumulation.symbol in candidates


def _section(markdown: str, title: str) -> str:
    marker = f"## {title}"
    start = markdown.index(marker)
    rest = markdown[start + len(marker):]
    next_section = rest.find("\n## ")
    return rest if next_section == -1 else rest[:next_section]


def _signal(
    symbol: str,
    fund_signal: FundSignal,
    pattern_tags: tuple[PatternTag, ...],
    score: float,
    main_flow: float,
    main_pct: float,
    change_pct: float,
) -> StockSignal:
    timestamp = datetime(2026, 7, 7, 10, 30)
    return StockSignal(
        symbol=symbol,
        name=symbol,
        timestamp=timestamp,
        fund_signal=fund_signal,
        pattern_tags=pattern_tags,
        anomalies=(),
        score=score,
        reasons=(),
        quote=Quote(
            symbol=symbol,
            name=symbol,
            price=10.0,
            change_pct=change_pct,
            timestamp=timestamp,
            provider="test",
            volume_ratio=1.2,
        ),
        fund_flow=FundFlowSnapshot(
            symbol=symbol,
            name=symbol,
            timestamp=timestamp,
            super_large_net_inflow=main_flow * 0.6,
            large_net_inflow=main_flow * 0.4,
            medium_net_inflow=0,
            small_net_inflow=-main_flow * 0.2,
            main_net_inflow_pct=main_pct,
            change_pct=change_pct,
            amount=100_000_000,
            turnover_rate=3.0,
            provider="test",
            period="daily",
        ),
    )
