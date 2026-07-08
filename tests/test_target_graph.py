from datetime import date

from wealth_lab.models import PortfolioSnapshot
from wealth_lab.replay import ReplayResult
from wealth_lab.target_graph import assess_target_return


def test_assess_target_return_flags_single_stock_sample_gap() -> None:
    result = ReplayResult(
        symbol="000620",
        name="盈新发展",
        bars_count=246,
        fund_flows_count=120,
        first_bar_date=date(2025, 7, 2),
        last_bar_date=date(2026, 7, 7),
        signals=[],
        decisions=[],
        fills=[],
        equity_curve=[
            PortfolioSnapshot(date(2026, 7, 7), 100420, 0, 100420, {})
        ],
        missing_fund_flow_dates=[],
        skipped_orders=[],
        initial_cash=100000,
        final_value=100420,
        total_return=0.0042,
        max_drawdown=0.0062,
    )

    assessment = assess_target_return(result, target_annual_return=0.10)

    assert assessment.actual_annualized_return_pct < 10
    assert assessment.gap_amount > 0
    assert assessment.conclusion == "not_enough_evidence_for_capital_allocation"
    statuses = {node.node_id: node.status for node in assessment.nodes}
    assert statuses["goal_gap"] == "block"
    assert statuses["sample_size"] == "block"
    assert statuses["risk_control"] == "pass"
