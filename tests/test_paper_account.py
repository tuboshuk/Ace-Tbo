from datetime import date

import pytest

from wealth_lab.models import Fill, OrderSide, PortfolioSnapshot
from wealth_lab.paper_account import (
    PaperAccountGoalModel,
    PortfolioPaperAccountConfig,
    build_portfolio_paper_account_report,
    build_paper_account_report,
    monthly_paper_account_rows,
    render_paper_account_report,
    render_portfolio_paper_account_report,
)
from wealth_lab.replay import ReplayResult


def test_monthly_paper_account_rows_mark_to_market_by_month() -> None:
    replay = _replay_with_months()

    rows = monthly_paper_account_rows(replay)

    assert [row.month for row in rows] == ["2025-07", "2025-08"]
    assert rows[0].start_value == 100000
    assert rows[0].end_value == 101000
    assert rows[0].return_pct == pytest.approx(1.0)
    assert rows[0].buy_fills == 1
    assert rows[0].sell_fills == 0
    assert rows[0].holding_days == 1
    assert rows[0].cash_days == 1
    assert rows[0].avg_capital_utilization_pct == pytest.approx(5.445545)
    assert rows[0].target_gap_pct == pytest.approx(-7.0)
    assert rows[1].start_value == 101000
    assert rows[1].end_value == 99000
    assert rows[1].return_pct == pytest.approx(-1.980198)
    assert rows[1].buy_fills == 0
    assert rows[1].sell_fills == 1


def test_render_paper_account_report_includes_summary_and_months() -> None:
    replay = _replay_with_months()
    report = build_paper_account_report(
        replay=replay,
        strategy="volume_price_breakout_opening_guard_probe",
        requested_start=date(2025, 7, 8),
        requested_end=date(2026, 7, 8),
        run_id="test-run",
    )

    text = render_paper_account_report(report)

    assert "Paper Account Replay - 000620" in text
    assert "total_return_pct: -1.0000%" in text
    assert "fund_flow_coverage: 0/4 (0.00%)" in text
    assert "monthly_target_return_pct: 8.00%" in text
    assert "cost_budget_pct: 30.00% of monthly target" in text
    assert "monthly_cost_budget_return_pct: 2.40%" in text
    assert "avg_monthly_target_gap_pct: -8.4901%" in text
    assert "capital_utilization" in text
    assert "| 2025-07 |" in text
    assert "| 2025-08 |" in text


def test_paper_account_report_accepts_custom_goal_model() -> None:
    report = build_paper_account_report(
        replay=_replay_with_months(),
        strategy="volume_price_breakout_opening_guard_probe",
        requested_start=date(2025, 7, 8),
        requested_end=date(2026, 7, 8),
        run_id="test-run",
        goal_model=PaperAccountGoalModel(
            monthly_target_return_pct=6.0,
            cost_budget_pct=25.0,
        ),
    )

    text = render_paper_account_report(report)

    assert "monthly_target_return_pct: 6.00%" in text
    assert "monthly_cost_budget_return_pct: 1.50%" in text
    assert "| 2025-07 | 2025-07-08 | 2025-07-31 | 100000.00 | 101000.00 | 1.0000% | -5.0000% |" in text


def test_monthly_paper_account_rows_requires_equity_curve() -> None:
    replay = _replay_with_months(equity_curve=[])

    with pytest.raises(ValueError, match="snapshots"):
        monthly_paper_account_rows(replay)


def test_build_portfolio_paper_account_report_uses_shared_cash() -> None:
    replay_a = _replay_with_months()
    replay_b = _replay_with_months(
        symbol="002031",
        fills=[
            Fill(
                symbol="002031",
                side=OrderSide.BUY,
                quantity=1000,
                price=20.0,
                trade_date=date(2025, 7, 30),
                gross_amount=20000,
                fees=0,
                reason="test_buy_b",
            ),
            Fill(
                symbol="002031",
                side=OrderSide.SELL,
                quantity=1000,
                price=24.0,
                trade_date=date(2025, 8, 29),
                gross_amount=24000,
                fees=0,
                reason="test_sell_b",
            ),
        ],
    )

    report = build_portfolio_paper_account_report(
        replays=(replay_a, replay_b),
        strategy="volume_price_breakout_opening_guard_probe",
        requested_start=date(2025, 7, 8),
        requested_end=date(2025, 8, 29),
        initial_cash=100000,
        config=PortfolioPaperAccountConfig(
            max_positions=2,
            min_buy_weight=0.05,
            max_position_weight=0.10,
        ),
        run_id="portfolio-test",
    )

    assert report.final_value > 100000
    assert len(report.fills) == 4
    assert report.monthly_rows[-1].end_value == report.final_value

    text = render_portfolio_paper_account_report(report)

    assert "Portfolio Paper Account Replay" in text
    assert "max_positions: 2" in text
    assert "monthly_target_return_pct: 8.00%" in text
    assert "avg_capital_utilization_pct:" in text
    assert "002031" in text


def test_portfolio_paper_account_can_force_twenty_percent_buy_weight() -> None:
    report = build_portfolio_paper_account_report(
        replays=(_replay_with_months(),),
        strategy="volume_price_breakout_opening_guard_probe",
        requested_start=date(2025, 7, 8),
        requested_end=date(2025, 8, 29),
        initial_cash=100000,
        config=PortfolioPaperAccountConfig(
            max_positions=1,
            min_buy_weight=0.20,
            max_position_weight=0.20,
        ),
        run_id="portfolio-high-risk-test",
    )

    buy = next(fill for fill in report.fills if fill.side == OrderSide.BUY)

    assert buy.gross_amount == 20000
    assert report.config.min_buy_weight == pytest.approx(0.20)
    assert report.config.max_position_weight == pytest.approx(0.20)


def _replay_with_months(
    equity_curve: list[PortfolioSnapshot] | None = None,
    *,
    symbol: str = "000620",
    fills: list[Fill] | None = None,
) -> ReplayResult:
    snapshots = (
        equity_curve
        if equity_curve is not None
        else [
            PortfolioSnapshot(date(2025, 7, 8), 100000, 0, 100000, {}),
            PortfolioSnapshot(date(2025, 7, 31), 90000, 11000, 101000, {symbol: 1000}),
            PortfolioSnapshot(date(2025, 8, 1), 90000, 10500, 100500, {symbol: 1000}),
            PortfolioSnapshot(date(2025, 8, 29), 99000, 0, 99000, {}),
        ]
    )
    return ReplayResult(
        symbol=symbol,
        name=symbol,
        bars_count=4,
        fund_flows_count=0,
        first_bar_date=date(2025, 7, 8),
        last_bar_date=date(2025, 8, 29),
        signals=[],
        decisions=[],
        fills=fills
        if fills is not None
        else [
            Fill(
                symbol=symbol,
                side=OrderSide.BUY,
                quantity=1000,
                price=10.0,
                trade_date=date(2025, 7, 30),
                gross_amount=10000,
                fees=0,
                reason="test_buy",
            ),
            Fill(
                symbol=symbol,
                side=OrderSide.SELL,
                quantity=1000,
                price=9.0,
                trade_date=date(2025, 8, 29),
                gross_amount=9000,
                fees=0,
                reason="test_sell",
            ),
        ],
        equity_curve=snapshots,
        missing_fund_flow_dates=[
            date(2025, 7, 8),
            date(2025, 7, 31),
            date(2025, 8, 1),
            date(2025, 8, 29),
        ],
        skipped_orders=[],
        initial_cash=100000,
        final_value=99000,
        total_return=-0.01,
        max_drawdown=0.02,
    )
