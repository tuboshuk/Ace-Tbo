from datetime import date, datetime, timedelta, timezone

from wealth_lab.accumulation_proof import (
    build_point_in_time_proof_context,
    build_accumulation_proof_report,
    render_accumulation_proof_report,
    write_accumulation_proof_report,
)
from wealth_lab.models import (
    FundFlowSnapshot,
    FundSignal,
    PatternTag,
    PortfolioSnapshot,
    Quote,
    StockSignal,
)
from wealth_lab.replay import ReplayResult


def test_accumulation_proof_confirms_when_future_support_flow_and_price_recover() -> None:
    start = date(2026, 1, 1)
    seed = _signal(start, 10.0, -1_000_000, 500_000, -2.0, (PatternTag.FAILED_BREAKOUT,))
    future = [
        _signal(start + timedelta(days=1), 9.8, 300_000, -200_000, -2.0, (PatternTag.NO_ACTION,)),
        _signal(start + timedelta(days=2), 10.4, 900_000, -300_000, 6.1, (PatternTag.NO_ACTION,)),
    ]

    report = build_accumulation_proof_report(
        replay=_result([seed, *future]),
        current_signal=seed,
        horizon=2,
        min_cases=1,
    )

    assert report.current_status == "pending_future_confirmation"
    assert report.confirmed == 1
    assert report.failed == 0
    assert report.confirmation_rate_pct == 100


def test_accumulation_proof_fails_when_support_breaks_and_flow_stays_out() -> None:
    start = date(2026, 1, 1)
    seed = _signal(start, 10.0, -1_000_000, 500_000, -2.0, (PatternTag.FAILED_BREAKOUT,))
    future = [
        _signal(start + timedelta(days=1), 9.6, -400_000, 200_000, -4.0, (PatternTag.NO_ACTION,)),
        _signal(start + timedelta(days=2), 9.3, -600_000, 300_000, -3.1, (PatternTag.NO_ACTION,)),
    ]

    report = build_accumulation_proof_report(
        replay=_result([seed, *future]),
        current_signal=seed,
        horizon=2,
        min_cases=1,
    )

    assert report.confirmed == 0
    assert report.failed == 1
    assert report.failure_rate_pct == 100
    assert report.conclusion == "historically_more_often_failed"


def test_accumulation_proof_ignores_non_candidate_current_signal() -> None:
    start = date(2026, 1, 1)
    signal = _signal(start, 10.0, 1_000_000, -300_000, 2.0, (PatternTag.NO_ACTION,))

    report = build_accumulation_proof_report(
        replay=_result([signal]),
        current_signal=signal,
        horizon=2,
    )

    assert report.current_status == "not_candidate"
    assert report.historical_cases == ()


def test_accumulation_proof_report_can_be_persisted(tmp_path) -> None:
    start = date(2026, 1, 1)
    seed = _signal(start, 10.0, -1_000_000, 500_000, -2.0, (PatternTag.FAILED_BREAKOUT,))
    future = [
        _signal(start + timedelta(days=1), 10.2, 300_000, -200_000, 2.0, (PatternTag.NO_ACTION,)),
        _signal(start + timedelta(days=2), 10.4, 300_000, -200_000, 2.0, (PatternTag.NO_ACTION,)),
    ]
    report = build_accumulation_proof_report(
        replay=_result([seed, *future]),
        current_signal=seed,
        horizon=2,
        min_cases=1,
    )
    rendered = render_accumulation_proof_report(report)

    output_path = write_accumulation_proof_report(
        report=report,
        output_dir=tmp_path,
        rendered=rendered,
        run_time=datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
    )

    assert output_path.name == "000001-2026-01-01-h2-20260102T030405Z.md"
    assert output_path.read_text(encoding="utf-8") == rendered


def test_point_in_time_context_uses_only_resolved_past_cases() -> None:
    start = date(2026, 1, 1)
    first_seed = _signal(start, 10.0, -1_000_000, 500_000, -2.0, (PatternTag.FAILED_BREAKOUT,))
    first_future = [
        _signal(start + timedelta(days=1), 10.1, 300_000, -200_000, 1.0, (PatternTag.NO_ACTION,)),
        _signal(start + timedelta(days=2), 10.4, 300_000, -200_000, 3.0, (PatternTag.NO_ACTION,)),
    ]
    current_seed = _signal(
        start + timedelta(days=3),
        10.0,
        -1_000_000,
        500_000,
        -2.0,
        (PatternTag.FAILED_BREAKOUT,),
    )

    context = build_point_in_time_proof_context(
        [first_seed, *first_future, current_seed],
        index=3,
        horizon=2,
        min_cases=1,
        min_confirmation_rate_pct=60.0,
    )

    assert context.resolved == 1
    assert context.confirmed == 1
    assert context.probe_allowed


def _result(signals: list[StockSignal]) -> ReplayResult:
    return ReplayResult(
        symbol="000001",
        name="test",
        bars_count=len(signals),
        fund_flows_count=len(signals),
        first_bar_date=signals[0].timestamp.date(),
        last_bar_date=signals[-1].timestamp.date(),
        signals=signals,
        decisions=[],
        fills=[],
        equity_curve=[
            PortfolioSnapshot(signals[-1].timestamp.date(), 100000, 0, 100000, {})
        ],
        missing_fund_flow_dates=[],
        skipped_orders=[],
        initial_cash=100000,
        final_value=100000,
        total_return=0,
        max_drawdown=0,
    )


def _signal(
    trade_date: date,
    price: float,
    main_flow: float,
    small_flow: float,
    change_pct: float,
    tags: tuple[PatternTag, ...],
) -> StockSignal:
    timestamp = datetime.combine(trade_date, datetime.min.time())
    return StockSignal(
        symbol="000001",
        name="test",
        timestamp=timestamp,
        fund_signal=FundSignal.SELL if main_flow < 0 else FundSignal.BUY,
        pattern_tags=tags,
        anomalies=(),
        score=80,
        reasons=(),
        quote=Quote(
            symbol="000001",
            name="test",
            price=price,
            change_pct=change_pct,
            timestamp=timestamp,
            provider="test",
        ),
        fund_flow=FundFlowSnapshot(
            symbol="000001",
            name="test",
            timestamp=timestamp,
            super_large_net_inflow=main_flow * 0.6,
            large_net_inflow=main_flow * 0.4,
            medium_net_inflow=0,
            small_net_inflow=small_flow,
            main_net_inflow_pct=main_flow / 10_000_000 * 100,
            change_pct=change_pct,
            amount=10_000_000,
            turnover_rate=5.0,
            provider="test",
            period="daily",
        ),
    )
