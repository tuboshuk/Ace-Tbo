import csv
from datetime import date, datetime, timedelta
from pathlib import Path

from wealth_lab.diagnostics import (
    KnowledgeHypothesisReview,
    PositionActionReview,
    TradeStory,
    TradeThesis,
)
from wealth_lab.models import Bar, FundFlowSnapshot, PortfolioSnapshot
from wealth_lab.replay import ReplayDecision, ReplayResult
from wealth_lab.training import (
    CandidateResult,
    FilterAttribution,
    LossAttribution,
    MissedOpportunity,
    PreBreakoutObservation,
    TradeDetail,
    TrainingRun,
    default_training_candidates,
    evaluate_training_candidates,
    render_large_pool_diagnosis,
    render_expansion_validation_summary,
    render_missed_breakout_opportunity_report,
    render_training_summary,
    run_replay_training,
    training_candidates_with_fast_failure_probe,
    training_candidates_with_main_force_profile_probe,
    training_candidates_with_watchlist_probe,
    _evidence_score,
    _missed_big_move_stats,
    _pre_breakout_watch_stats,
    _promotion_decision,
    write_large_pool_diagnosis,
    write_training_artifacts,
)


def test_evaluate_training_candidates_returns_comparable_results() -> None:
    run_id = "test-run"
    bars, flows = _dataset()

    results = evaluate_training_candidates(
        run_id=run_id,
        symbol="000001",
        bars=bars,
        fund_flows=flows,
        initial_cash=100000,
        target_annual_return=0.10,
        candidates=default_training_candidates(),
    )

    assert len(results) == 1
    assert {item.run_id for item in results} == {run_id}
    assert {item.symbol for item in results} == {"000001"}
    assert all(item.bars_count == len(bars) for item in results)
    assert all(item.fund_flows_count == len(flows) for item in results)
    assert all(0 <= item.evidence_score <= 100 for item in results)
    assert all(item.trading_mode for item in results)
    assert all(item.behavior_phase for item in results)
    assert all(item.fund_flow_bias for item in results)


def test_evaluate_training_candidates_allows_missing_fund_flow_data() -> None:
    bars, _ = _dataset()

    [result] = evaluate_training_candidates(
        run_id="missing-flow-run",
        symbol="000001",
        bars=bars,
        fund_flows=[],
        initial_cash=100000,
        target_annual_return=0.10,
        candidates=default_training_candidates(),
    )

    assert result.fund_flows_count == 0
    assert result.missing_fund_flow_dates == len(bars)
    assert result.trading_mode == "WAIT_DATA"
    assert result.behavior_phase == "no_fund_flow_signal"


def test_run_replay_training_rejects_non_positive_workers(tmp_path: Path) -> None:
    try:
        run_replay_training(
            symbols=["000001"],
            days=30,
            initial_cash=100000,
            target_annual_return=0.10,
            output_dir=tmp_path,
            max_workers=0,
        )
    except ValueError as exc:
        assert "max_workers" in str(exc)
    else:
        raise AssertionError("expected max_workers validation")


def test_render_training_summary_lists_candidate_hypotheses() -> None:
    bars, flows = _dataset()
    results = evaluate_training_candidates(
        run_id="summary-run",
        symbol="000001",
        bars=bars,
        fund_flows=flows,
        initial_cash=100000,
        target_annual_return=0.10,
        candidates=default_training_candidates()[:1],
    )
    training_run = TrainingRun(
        run_id="summary-run",
        created_at="2026-07-07T00:00:00+00:00",
        symbols=("000001",),
        days=120,
        initial_cash=100000,
        target_annual_return=0.10,
        candidates=("volume_price_breakout_opening_guard_probe",),
        results=tuple(results),
        errors=(),
        jsonl_path=Path("training.jsonl"),
        summary_path=Path("summary.md"),
    )

    summary = render_training_summary(training_run)

    assert "volume_price_breakout_opening_guard_probe" in summary
    assert "Candidate Aggregate" in summary
    assert "Candidate Promotion Gate" in summary
    assert "Candidate Tiers" in summary
    assert "Loss Attribution Summary" in summary
    assert "Position Action Replay" in summary
    assert "Knowledge Hypothesis Diagnostics" in summary
    assert "Latest behavior state by candidate" in summary
    assert "Capital Utilization" in summary
    assert "Execution Target Bands" in summary
    assert "Filter Attribution" in summary
    assert "Missed Big Move Diagnostics" in summary
    assert "Data Coverage" in summary
    assert "Pre-Breakout Observation Layer" in summary
    assert "core" in summary
    assert "sample" in summary
    assert "simulated research only" in summary


def test_training_jsonl_persists_parseable_trade_details(tmp_path: Path) -> None:
    training_run = TrainingRun(
        run_id="jsonl-run",
        created_at="2026-07-09T00:00:00+00:00",
        symbols=("000001",),
        days=120,
        initial_cash=100000,
        target_annual_return=0.10,
        candidates=("volume_price_breakout_opening_guard_probe",),
        results=(
            _candidate_result(
                candidate="volume_price_breakout_opening_guard_probe",
                tier="core",
                symbol="000001",
                trade_details=(
                    TradeDetail(
                        trade_id="jsonl-run-000001-001",
                        symbol="000001",
                        entry_date="2026-01-02",
                        exit_date="2026-01-05",
                        quantity=1000,
                        entry_price=10.0,
                        exit_price=10.5,
                        net_pnl=500.0,
                        return_pct=5.0,
                        holding_days=3,
                        entry_reason="entry",
                        exit_reason="exit",
                    ),
                ),
            ),
        ),
        errors=(),
        jsonl_path=tmp_path / "training.jsonl",
        summary_path=tmp_path / "summary.md",
    )

    write_training_artifacts(training_run)

    import json

    rows = [json.loads(line) for line in training_run.jsonl_path.read_text().splitlines()]
    result = next(row for row in rows if row["kind"] == "candidate_result")
    assert result["trade_details"][0]["trade_id"] == "jsonl-run-000001-001"

    csv_path = tmp_path / "training-trade-details.csv"
    markdown_path = tmp_path / "training-trade-details.md"
    csv_text = csv_path.read_text(encoding="utf-8-sig")
    markdown_text = markdown_path.read_text(encoding="utf-8")

    assert csv_path.exists()
    assert markdown_path.exists()
    assert "trade_id,run_id,candidate,tier,symbol,initial_cash,buy_date,sell_date" in csv_text
    assert "profit,loss,net_pnl" in csv_text
    assert "# Trade Details" in markdown_text
    assert "jsonl-run-000001-001" in markdown_text
    [trade_row] = list(csv.DictReader(csv_text.splitlines()))
    assert trade_row["trade_id"] == "jsonl-run-000001-001"
    assert trade_row["run_id"] == "jsonl-run"
    assert trade_row["candidate"] == "volume_price_breakout_opening_guard_probe"
    assert trade_row["tier"] == "core"
    assert trade_row["symbol"] == "000001"
    assert trade_row["initial_cash"] == "100000"
    assert trade_row["buy_date"] == "2026-01-02"
    assert trade_row["sell_date"] == "2026-01-05"
    assert trade_row["profit"] == "500.0"
    assert trade_row["loss"] == "0.0"
    assert trade_row["net_pnl"] == "500.0"


def test_large_pool_diagnosis_reports_profiles_and_trade_ledger(tmp_path: Path) -> None:
    jsonl_path = tmp_path / "training.jsonl"
    training_run = TrainingRun(
        run_id="diagnosis-run",
        created_at="2026-07-09T00:00:00+00:00",
        symbols=("000001",),
        days=120,
        initial_cash=100000,
        target_annual_return=0.10,
        candidates=("volume_price_breakout_opening_guard_probe",),
        results=(
            _candidate_result(
                candidate="volume_price_breakout_opening_guard_probe",
                tier="core",
                symbol="000001",
                trade_details=(
                    TradeDetail(
                        trade_id="diagnosis-run-000001-001",
                        symbol="000001",
                        entry_date="2026-01-02",
                        exit_date="2026-01-05",
                        quantity=1000,
                        entry_price=10.0,
                        exit_price=9.5,
                        net_pnl=-500.0,
                        return_pct=-5.0,
                        holding_days=3,
                        entry_reason="entry",
                        exit_reason="stop",
                    ),
                ),
            ),
        ),
        errors=(),
        jsonl_path=jsonl_path,
        summary_path=tmp_path / "summary.md",
    )
    write_training_artifacts(training_run)

    report = render_large_pool_diagnosis(jsonl_path=jsonl_path)
    output_path = write_large_pool_diagnosis(jsonl_path=jsonl_path)
    csv_path = tmp_path / "training-trade-details.csv"
    markdown_path = tmp_path / "training-trade-details.md"

    assert "Large Pool Diagnosis diagnosis-run" in report
    assert "initial_cash: 100000.00" in report
    assert "Candidate Summary" in report
    assert "trade_details_csv:" in report
    assert "Phase / Fund State / Board" in report
    assert "OBSERVE: sample < 30" in report
    assert "Trade Ledger" in report
    assert "diagnosis-run-000001-001" in report
    assert output_path.exists()
    assert csv_path.exists()
    assert markdown_path.exists()
    assert "diagnosis-run-000001-001" in csv_path.read_text(encoding="utf-8-sig")
    assert "loss" in csv_path.read_text(encoding="utf-8-sig")
    assert "diagnosis-run-000001-001" in markdown_path.read_text(encoding="utf-8")


def test_large_pool_diagnosis_reads_legacy_trade_ledger_csv(tmp_path: Path) -> None:
    jsonl_path = tmp_path / "legacy-run-training.jsonl"
    training_run = TrainingRun(
        run_id="legacy-run",
        created_at="2026-07-09T00:00:00+00:00",
        symbols=("000001",),
        days=120,
        initial_cash=100000,
        target_annual_return=0.10,
        candidates=("volume_price_breakout_opening_guard_probe",),
        results=(
            _candidate_result(
                candidate="volume_price_breakout_opening_guard_probe",
                tier="core",
                symbol="000001",
            ),
        ),
        errors=(),
        jsonl_path=jsonl_path,
        summary_path=tmp_path / "summary.md",
    )
    write_training_artifacts(training_run)
    (tmp_path / "legacy-run-trade-ledger.csv").write_text(
        "\n".join(
            (
                "trade_id,run_id,candidate,tier,symbol,initial_cash,signal_date,buy_date,sell_date,holding_days,return_pct,result,profit_loss_amount,entry_reason,exit_reason",
                "legacy-run-000001-001,legacy-run,volume_price_breakout_opening_guard_probe,core,000001,100000,2026-01-01,2026-01-02,2026-01-05,3,4.5,profit,not_persisted,entry,exit",
            )
        ),
        encoding="utf-8",
    )

    report = render_large_pool_diagnosis(jsonl_path=jsonl_path)

    assert "- all: trades=1 wins=1 losses=0" in report
    assert "legacy-run-000001-001" in report
    assert "2026-01-02" in report


def test_promotion_decision_keeps_small_samples_in_observe() -> None:
    for closed in (12, 24):
        decision, reason = _promotion_decision(
            _promotion_aggregate(
                closed=closed,
                traded_symbols=2,
                avg_expectancy=1.0,
                avg_return=4.0,
            )
        )

        assert decision == "OBSERVE"
        assert "30" in reason


def test_promotion_decision_requires_multi_symbol_positive_cost_buffer() -> None:
    one_symbol_decision, one_symbol_reason = _promotion_decision(
        _promotion_aggregate(
            closed=31,
            traded_symbols=1,
            avg_expectancy=1.0,
            avg_return=4.0,
        )
    )
    weak_edge_decision, weak_edge_reason = _promotion_decision(
        _promotion_aggregate(
            closed=31,
            traded_symbols=2,
            avg_expectancy=0.20,
            avg_return=4.0,
        )
    )
    negative_return_decision, negative_return_reason = _promotion_decision(
        _promotion_aggregate(
            closed=31,
            traded_symbols=2,
            avg_expectancy=1.0,
            avg_return=-0.1,
        )
    )
    low_utilization_decision, low_utilization_reason = _promotion_decision(
        _promotion_aggregate(
            closed=31,
            traded_symbols=2,
            avg_expectancy=1.0,
            avg_return=12.0,
            holding_utilization_pct=0.5,
        )
    )
    low_position_decision, low_position_reason = _promotion_decision(
        _promotion_aggregate(
            closed=31,
            traded_symbols=2,
            avg_expectancy=1.0,
            avg_return=12.0,
            avg_position_pct=0.05,
        )
    )
    below_target_decision, below_target_reason = _promotion_decision(
        _promotion_aggregate(
            closed=31,
            traded_symbols=2,
            avg_expectancy=1.0,
            avg_return=4.0,
        )
    )
    promote_decision, promote_reason = _promotion_decision(
        _promotion_aggregate(
            closed=31,
            traded_symbols=2,
            avg_expectancy=0.75,
            avg_return=12.0,
        )
    )

    assert one_symbol_decision == "OBSERVE"
    assert "multi-symbol" in one_symbol_reason
    assert weak_edge_decision == "OBSERVE"
    assert "cost/slippage" in weak_edge_reason
    assert negative_return_decision == "OBSERVE"
    assert "positive" in negative_return_reason
    assert low_utilization_decision == "OBSERVE"
    assert "holding utilization" in low_utilization_reason
    assert low_position_decision == "OBSERVE"
    assert "average position" in low_position_reason
    assert below_target_decision == "OBSERVE"
    assert "annual target" in below_target_reason
    assert promote_decision == "PROMOTE_CANDIDATE"
    assert "target-return" in promote_reason


def test_render_training_summary_lists_tiers_and_loss_attribution() -> None:
    training_run = TrainingRun(
        run_id="loss-summary",
        created_at="2026-07-07T00:00:00+00:00",
        symbols=("002031", "000001"),
        days=240,
        initial_cash=100000,
        target_annual_return=0.10,
        candidates=(
            "volume_price_support_quality_probe",
            "volume_price_trial_probe",
        ),
        results=(
            _candidate_result(
                candidate="volume_price_support_quality_probe",
                tier="core",
                symbol="002031",
                loss_attributions=(
                    LossAttribution(
                        symbol="002031",
                        entry_reason="volume_price_trial_entry: noise buy",
                        volume_node="quiet_consolidation",
                        trades=3,
                        avg_loss_return_pct=-1.25,
                        total_pnl=-375.0,
                        worst_return_pct=-2.1,
                    ),
                ),
            ),
            _candidate_result(
                candidate="volume_price_trial_probe",
                tier="experimental",
                symbol="000001",
            ),
        ),
        errors=(),
        jsonl_path=Path("training.jsonl"),
        summary_path=Path("summary.md"),
    )

    summary = render_training_summary(training_run)

    assert "Candidate Tiers" in summary
    assert "core: volume_price_support_quality_probe" in summary
    assert "experimental: volume_price_trial_probe" in summary
    assert "Loss Attribution Summary" in summary
    assert "002031" in summary
    assert "volume_price_trial_entry: noise buy" in summary
    assert "quiet_consolidation" in summary


def test_render_training_summary_lists_trade_thesis_stories() -> None:
    story = TradeStory(
        symbol="002031",
        signal_date="2026-06-01",
        entry_date="2026-06-02",
        exit_date="2026-06-05",
        entry_reason="volume_price_trial_entry: node=dry_up_base",
        exit_reason="volume_price_scheduled_exit",
        return_pct=2.5,
        actual_holding_days=3,
        thesis=TradeThesis(
            entry_family="volume_price_trial_entry",
            buy_type="dry_up_absorption_test",
            vpa_archetype="dry_up_no_supply_absorption",
            stage="accumulation",
            expected_holding_days="3-5 bars",
            expected_follow_through="dry-up should stop falling first",
            invalidation_price=7.86,
            take_profit_logic="hold while support is respected",
            must_hold_conditions=("price does not close below support",),
            must_exit_conditions=("close below invalidation price",),
        ),
        confirmations=2,
        warnings=0,
        invalidations=0,
        holding_evidence="d1:confirming:quiet_hold; d2:confirming:close_above_entry",
        verdict="thesis_confirmed",
    )
    training_run = TrainingRun(
        run_id="story-summary",
        created_at="2026-07-07T00:00:00+00:00",
        symbols=("002031",),
        days=240,
        initial_cash=100000,
        target_annual_return=0.10,
        candidates=("volume_price_support_quality_probe",),
        results=(
            _candidate_result(
                candidate="volume_price_support_quality_probe",
                tier="core",
                symbol="002031",
                trade_stories=(story,),
            ),
        ),
        errors=(),
        jsonl_path=Path("training.jsonl"),
        summary_path=Path("summary.md"),
    )

    summary = render_training_summary(training_run)

    assert "Trade Thesis Stories" in summary
    assert "dry_up_absorption_test" in summary
    assert "dry_up_no_supply_absorption" in summary
    assert "3-5 bars" in summary
    assert "thesis_confirmed" in summary
    assert "d1:confirming:quiet_hold" in summary


def test_render_training_summary_aggregates_position_action_reviews() -> None:
    reviews = (
        PositionActionReview(
            symbol="002031",
            signal_date="2026-06-01",
            entry_date="2026-06-02",
            exit_date="2026-06-05",
            return_pct=2.0,
            gap_pct=1.0,
            gap_bucket=1,
            opening_classification="expected_open",
            support_distance_pct=2.0,
            position_action="probe_30",
            action_reason="expected_open_with_usable_support",
        ),
        PositionActionReview(
            symbol="002031",
            signal_date="2026-06-08",
            entry_date="2026-06-09",
            exit_date="2026-06-12",
            return_pct=4.0,
            gap_pct=None,
            gap_bucket=None,
            opening_classification="insufficient_opening_history",
            support_distance_pct=4.0,
            position_action="probe_30",
            action_reason="expected_open_with_usable_support",
        ),
    )
    training_run = TrainingRun(
        run_id="action-summary",
        created_at="2026-07-07T00:00:00+00:00",
        symbols=("002031",),
        days=240,
        initial_cash=100000,
        target_annual_return=0.10,
        candidates=("volume_price_support_quality_probe",),
        results=(
            _candidate_result(
                candidate="volume_price_support_quality_probe",
                tier="core",
                symbol="002031",
                position_action_reviews=reviews,
            ),
        ),
        errors=(),
        jsonl_path=Path("training.jsonl"),
        summary_path=Path("summary.md"),
    )

    summary = render_training_summary(training_run)

    assert "Position Action Replay" in summary
    assert (
        "volume_price_support_quality_probe | core | probe_30 | 2 | 3.00% | 1.00% | 3.00%"
        in summary
    )


def test_render_training_summary_aggregates_knowledge_hypothesis_reviews() -> None:
    reviews = tuple(
        KnowledgeHypothesisReview(
            symbol="002031",
            entry_date=f"2026-06-{day:02d}",
            source_id="coulling_wyckoff_weis",
            lens="volume_price",
            hypothesis_id="effort_result_must_confirm_stage",
            bucket="dry_up_no_supply_absorption",
            return_pct=return_pct,
            verdict=verdict,
            diagnostic_status="CONFIRMED_OBSERVATION"
            if verdict == "thesis_confirmed"
            else "FAILED_OBSERVATION",
        )
        for day, return_pct, verdict in (
            (1, 2.0, "thesis_confirmed"),
            (2, 1.0, "thesis_confirmed"),
            (3, 0.5, "thesis_confirmed"),
            (4, -0.2, "warnings_confirmed_exit"),
            (5, 1.2, "thesis_confirmed"),
        )
    )
    training_run = TrainingRun(
        run_id="knowledge-summary",
        created_at="2026-07-07T00:00:00+00:00",
        symbols=("002031",),
        days=240,
        initial_cash=100000,
        target_annual_return=0.10,
        candidates=("volume_price_support_quality_probe",),
        results=(
            _candidate_result(
                candidate="volume_price_support_quality_probe",
                tier="core",
                symbol="002031",
                knowledge_hypothesis_reviews=reviews,
            ),
        ),
        errors=(),
        jsonl_path=Path("training.jsonl"),
        summary_path=Path("summary.md"),
    )

    summary = render_training_summary(training_run)

    assert "Knowledge Hypothesis Diagnostics" in summary
    assert "volume_price | effort_result_must_confirm_stage" in summary
    assert "dry_up_no_supply_absorption | 5 | 80.00% | 0.90% | 4 | 0 | REVIEW_CANDIDATE" in summary


def test_render_training_summary_lists_capital_utilization_and_filters() -> None:
    training_run = TrainingRun(
        run_id="utilization-summary",
        created_at="2026-07-07T00:00:00+00:00",
        symbols=("002031",),
        days=120,
        initial_cash=100000,
        target_annual_return=0.10,
        candidates=("volume_price_breakout_opening_guard_probe",),
        results=(
            _candidate_result(
                candidate="volume_price_breakout_opening_guard_probe",
                tier="experimental",
                symbol="002031",
                holding_days=10,
                cash_days=90,
                avg_position_pct=2.5,
                max_position_pct=12.0,
                buy_signal_count=6,
                filtered_buy_signals=4,
                raw_filtered_observations=7,
                ordinary_non_signal_days=3,
                top_filter_reason="node_not_allowed",
                top_filter_count=3,
                filter_attributions=(
                    FilterAttribution("node_not_allowed", 3),
                    FilterAttribution("opening_above_expected_range", 1),
                ),
                missed_big_moves=5,
                missed_big_moves_filtered=2,
                missed_big_moves_ordinary_non_signal=1,
                missed_big_moves_unrecognized=2,
                top_missed_big_move_reason="no_buy_signal",
                missed_opportunity_attributions=(
                    FilterAttribution("opening_guard_cancel", 1),
                ),
                missed_opportunities=(
                    MissedOpportunity(
                        symbol="002031",
                        signal_date="2026-01-02",
                        close=10.0,
                        next_1d_close_return_pct=4.0,
                        next_3d_close_return_pct=12.0,
                        next_5d_close_return_pct=9.0,
                        max_forward_return_pct=14.0,
                        max_forward_date="2026-01-05",
                        max_forward_drawdown_pct=-2.0,
                        attribution="opening_guard_cancel",
                        detail_reason="breakout_opening_gap_too_high",
                        volume_node="volume_breakout",
                        volume_probe_passed=True,
                    ),
                ),
                pre_breakout_watch_count=2,
                pre_breakout_confirmed_count=1,
                pre_breakout_handoff_count=1,
                pre_breakout_observations=(
                    PreBreakoutObservation(
                        symbol="002031",
                        watch_date="2026-01-01",
                        watch_node="quiet_consolidation",
                        close=9.8,
                        next_1d_close_return_pct=1.5,
                        next_3d_close_return_pct=8.0,
                        next_5d_close_return_pct=12.0,
                        max_forward_return_pct=12.0,
                        max_forward_date="2026-01-05",
                        max_forward_drawdown_pct=-1.0,
                        confirmation_date="2026-01-03",
                        stage2_action="handoff_to_opening_guard",
                        confirmation_reason="volume_price_trial_entry: node=volume_breakout",
                        price_stood=True,
                        volume_expanded=True,
                        main_flow_state="not_weak",
                    ),
                ),
                trade_stories=(
                    _trade_story("002031", "2026-01-02", "2026-01-05", 10.0),
                    _trade_story("002031", "2026-02-02", "2026-02-05", 5.0),
                    _trade_story("002031", "2026-03-02", "2026-03-05", -2.0),
                ),
            ),
        ),
        errors=(),
        jsonl_path=Path("training.jsonl"),
        summary_path=Path("summary.md"),
        pool_source="random_efinance_spot",
        pool_seed=20260708,
        pool_eligible_symbols=4000,
    )

    summary = render_training_summary(training_run)

    assert "symbols_count: 1" in summary
    assert "pool_source: random_efinance_spot" in summary
    assert "pool_seed: 20260708" in summary
    assert "Capital Utilization" in summary
    assert (
        "volume_price_breakout_opening_guard_probe | core | 1 | 100 | 10 | 10.00% | 10.0 | 90 | 2.50% | 12.00% | 6 | 4 | 7 | 3 | node_not_allowed | 3 | 5 | 2 | 1 | 2"
        in summary
    )
    assert "Filter Attribution" in summary
    assert "node_not_allowed | 3" in summary
    assert "Trade Return Concentration" in summary
    assert (
        "volume_price_breakout_opening_guard_probe | experimental | 3 | 2 | 1 | 4.33% | 10.00% | -2.00% | 66.67% | 100.00%"
        in summary
    )
    assert "Missed Big Move Diagnostics" in summary
    assert "Missed Opportunity Attribution" in summary
    assert "opening_guard_cancel | 1" in summary
    assert "Missed Opportunity Detail" in summary
    assert (
        "volume_price_breakout_opening_guard_probe | experimental | 002031 | 2026-01-02 | 10.00 | 4.00% | 12.00% | 9.00% | 14.00% | -2.00% | 2026-01-05 | opening_guard_cancel | volume_breakout | breakout_opening_gap_too_high"
        in summary
    )
    assert "Pre-Breakout Observation Layer" in summary
    assert "quiet_consolidation" in summary
    assert "handoff_to_opening_guard" in summary
    assert "opening_guard_cancel" in summary

    missed_report = render_missed_breakout_opportunity_report(training_run)

    assert "Missed Breakout Opportunity Report" in missed_report
    assert "max_drawdown" in missed_report
    assert "blocked_next_open" in missed_report
    assert "Pre-Breakout Watchlist Candidates" in missed_report

    expansion_summary = render_expansion_validation_summary((training_run,))

    assert "Strategy Expansion Validation" in expansion_summary
    assert "top1_win_contribution" in expansion_summary


def test_missed_big_move_counts_opening_guard_cancel_as_not_bought() -> None:
    start = date(2026, 1, 1)
    bars = [
        _bar("000001", start + timedelta(days=index), close)
        for index, close in enumerate((10.0, 11.2, 11.3, 11.8, 11.1, 10.9))
    ]
    replay = ReplayResult(
        symbol="000001",
        name="test",
        bars_count=len(bars),
        fund_flows_count=len(bars),
        first_bar_date=bars[0].trade_date,
        last_bar_date=bars[-1].trade_date,
        signals=[],
        decisions=[
            ReplayDecision(
                signal_date=bars[0].trade_date,
                symbol="000001",
                fund_signal="volume_price",
                pattern_tags=("volume_breakout",),
                side="BUY",
                reason=(
                    "volume_price_trial_entry: node=volume_breakout "
                    "cases=5 win=80.00% avg=1.20%; passed_same_node_history_gate"
                ),
                observation_type="volume_price",
                volume_node="volume_breakout",
                volume_probe_passed=True,
            )
        ],
        fills=[],
        equity_curve=[
            PortfolioSnapshot(
                trade_date=bar.trade_date,
                cash=100000,
                market_value=0,
                total_value=100000,
            )
            for bar in bars
        ],
        missing_fund_flow_dates=[],
        skipped_orders=[
            (
                f"{bars[1].trade_date}: volume_price_opening_cancel: "
                "breakout_opening_gap_too_high max=3.00% gap=4.20%; "
                "original=volume_price_trial_entry: node=volume_breakout"
            )
        ],
        initial_cash=100000,
        final_value=100000,
        total_return=0,
        max_drawdown=0,
        bars=bars,
    )

    stats = _missed_big_move_stats(replay, include_details=True)

    assert stats["missed_big_moves"] == 1
    assert stats["missed_big_moves_filtered"] == 1
    assert stats["top_missed_big_move_reason"] == "opening_guard_cancel"
    assert stats["missed_opportunity_attributions"] == (
        FilterAttribution("opening_guard_cancel", 1),
    )
    [opportunity] = stats["missed_opportunities"]
    assert opportunity.attribution == "opening_guard_cancel"
    assert opportunity.volume_node == "volume_breakout"
    assert opportunity.max_forward_return_pct == 18.0
    assert "breakout_opening_gap_too_high" in opportunity.detail_reason


def test_pre_breakout_watch_stats_marks_observation_then_handoff() -> None:
    start = date(2026, 1, 1)
    bars = [
        _bar("000001", start + timedelta(days=index), close, volume=volume)
        for index, (close, volume) in enumerate(
            (
                (10.0, 1_000_000),
                (10.3, 1_000_000),
                (10.9, 2_000_000),
                (11.2, 1_800_000),
                (11.4, 1_400_000),
                (11.0, 1_000_000),
            )
        )
    ]
    replay = ReplayResult(
        symbol="000001",
        name="test",
        bars_count=len(bars),
        fund_flows_count=1,
        first_bar_date=bars[0].trade_date,
        last_bar_date=bars[-1].trade_date,
        signals=[],
        decisions=[
            ReplayDecision(
                signal_date=bars[0].trade_date,
                symbol="000001",
                fund_signal="volume_price",
                pattern_tags=("quiet_consolidation",),
                side=None,
                reason="volume_price_trial_blocked: node=quiet_consolidation",
                observation_type="volume_price",
                volume_node="quiet_consolidation",
                volume_probe_passed=False,
            ),
            ReplayDecision(
                signal_date=bars[2].trade_date,
                symbol="000001",
                fund_signal="volume_price",
                pattern_tags=("volume_breakout",),
                side="BUY",
                reason="volume_price_trial_entry: node=volume_breakout",
                observation_type="volume_price",
                volume_node="volume_breakout",
                volume_probe_passed=True,
            ),
        ],
        fills=[],
        equity_curve=[
            PortfolioSnapshot(
                trade_date=bar.trade_date,
                cash=100000,
                market_value=0,
                total_value=100000,
            )
            for bar in bars
        ],
        missing_fund_flow_dates=[],
        skipped_orders=[],
        initial_cash=100000,
        final_value=100000,
        total_return=0,
        max_drawdown=0,
        bars=bars,
        fund_flows=[_flow(bars[2].trade_date, 1_000_000, 0, 0, 1.0, 3.0)],
    )

    stats = _pre_breakout_watch_stats(replay, include_details=True)

    assert stats["watch_count"] == 1
    assert stats["confirmed_count"] == 1
    assert stats["handoff_count"] == 1
    [observation] = stats["observations"]
    assert observation.watch_node == "quiet_consolidation"
    assert observation.confirmation_date == bars[2].trade_date.isoformat()
    assert observation.stage2_action == "handoff_to_opening_guard"
    assert observation.price_stood is True
    assert observation.volume_expanded is True
    assert observation.main_flow_state == "not_weak"


def test_evidence_score_caps_no_closed_trade_runs() -> None:
    score = _evidence_score(
        sample_quality="no_closed_trades",
        closed_trades=0,
        expectancy_pct=None,
        total_return_pct=0.0,
        max_drawdown_pct=0.0,
        data_coverage_pct=100.0,
    )

    assert score == 0.0


def test_evidence_score_does_not_reward_repeatable_negative_expectancy() -> None:
    score = _evidence_score(
        sample_quality="low_confidence",
        closed_trades=23,
        expectancy_pct=-0.97,
        total_return_pct=-2.32,
        max_drawdown_pct=2.58,
        data_coverage_pct=49.0,
    )

    assert score == 0.0


def test_default_candidates_only_keep_opening_guard_probe() -> None:
    candidates = default_training_candidates()
    by_name = {item.name: item for item in candidates}

    assert tuple(by_name) == ("volume_price_breakout_opening_guard_probe",)
    breakout_opening_guard_config = by_name[
        "volume_price_breakout_opening_guard_probe"
    ].config
    assert by_name["volume_price_breakout_opening_guard_probe"].tier == "core"
    assert breakout_opening_guard_config.volume_price_probe_allowed_node_types == (
        "volume_breakout",
    )
    assert breakout_opening_guard_config.enable_volume_price_follow_through_exit
    assert (
        breakout_opening_guard_config.volume_price_breakout_max_opening_gap_pct
        == 3.0
    )
    assert (
        breakout_opening_guard_config.volume_price_breakout_wide_support_distance_pct
        == 8.0
    )
    assert (
        breakout_opening_guard_config.volume_price_breakout_min_gap_for_wide_support_pct
        == 0.5
    )
    assert breakout_opening_guard_config.enable_volume_price_risk_sizing
    assert breakout_opening_guard_config.enable_volume_price_intent_filter
    assert breakout_opening_guard_config.volume_price_block_non_breakout_markdown


def test_watchlist_candidates_keep_core_and_add_two_stage_experiment() -> None:
    candidates = training_candidates_with_watchlist_probe()
    by_name = {item.name: item for item in candidates}

    assert tuple(by_name) == (
        "volume_price_breakout_opening_guard_probe",
        "volume_price_pre_breakout_watchlist_opening_guard_probe",
    )
    core = by_name["volume_price_breakout_opening_guard_probe"]
    watchlist = by_name["volume_price_pre_breakout_watchlist_opening_guard_probe"]

    assert core.tier == "core"
    assert watchlist.tier == "experimental"
    assert watchlist.config.enable_volume_price_pre_breakout_watchlist_entry
    assert watchlist.config.volume_price_pre_breakout_observation_weight == 0.05
    assert watchlist.config.volume_price_pre_breakout_strong_weight == 0.10
    assert watchlist.config.volume_price_pre_breakout_continuous_weight == 0.15
    assert watchlist.config.volume_price_risk_sizing_respects_decision_cap
    assert watchlist.config.enable_volume_price_follow_through_exit
    assert watchlist.config.volume_price_follow_through_no_confirm_bars == 2
    assert watchlist.config.volume_price_breakout_max_opening_gap_pct == 3.0


def test_main_force_profile_candidates_keep_core_and_add_research_filter() -> None:
    candidates = training_candidates_with_main_force_profile_probe()
    by_name = {item.name: item for item in candidates}

    assert tuple(by_name) == (
        "volume_price_breakout_opening_guard_probe",
        "volume_price_main_force_profile_filter_probe",
        "volume_price_fast_failure_cut_probe",
        "volume_price_weak_main_force_fast_cut_probe",
    )
    core = by_name["volume_price_breakout_opening_guard_probe"]
    profile_filter = by_name["volume_price_main_force_profile_filter_probe"]
    fast_cut = by_name["volume_price_fast_failure_cut_probe"]
    weak_main_force_fast_cut = by_name[
        "volume_price_weak_main_force_fast_cut_probe"
    ]

    assert core.tier == "core"
    assert profile_filter.tier == "experimental"
    assert profile_filter.config.enable_volume_price_main_force_profile_filter
    assert profile_filter.config.volume_price_main_force_allowed_stages == (
        "accumulation_watch",
        "markup_confirmed",
    )
    assert profile_filter.config.volume_price_follow_through_no_confirm_bars == 2
    assert profile_filter.config.volume_price_follow_through_exit_on_negative_main_flow
    assert fast_cut.tier == "experimental"
    assert fast_cut.config.stop_loss_pct == 0.04
    assert fast_cut.config.volume_price_follow_through_no_confirm_bars == 1
    assert fast_cut.config.volume_price_follow_through_exit_on_negative_main_flow
    assert weak_main_force_fast_cut.tier == "experimental"
    assert weak_main_force_fast_cut.config.enable_volume_price_weak_main_force_block
    assert weak_main_force_fast_cut.config.stop_loss_pct == 0.04
    assert (
        weak_main_force_fast_cut.config.volume_price_weak_main_force_block_stages
        == ("distribution_risk", "failed_breakout")
    )
    assert (
        weak_main_force_fast_cut.config.volume_price_follow_through_no_confirm_bars
        == 1
    )


def test_fast_failure_candidates_skip_strict_main_force_filter() -> None:
    candidates = training_candidates_with_fast_failure_probe()
    by_name = {item.name: item for item in candidates}

    assert tuple(by_name) == (
        "volume_price_breakout_opening_guard_probe",
        "volume_price_fast_failure_cut_probe",
        "volume_price_weak_main_force_fast_cut_probe",
    )
    assert "volume_price_main_force_profile_filter_probe" not in by_name
    assert by_name["volume_price_breakout_opening_guard_probe"].tier == "core"
    assert by_name["volume_price_fast_failure_cut_probe"].tier == "experimental"
    assert (
        by_name["volume_price_weak_main_force_fast_cut_probe"].tier
        == "experimental"
    )


def _promotion_aggregate(
    *,
    closed: int,
    traded_symbols: int,
    avg_expectancy: float | None,
    avg_return: float,
    holding_utilization_pct: float = 5.0,
    avg_position_pct: float = 2.0,
    target_return_pct: float = 10.0,
) -> dict[str, object]:
    return {
        "candidate": "candidate",
        "tier": "core",
        "symbols": 2,
        "traded_symbols": traded_symbols,
        "closed": closed,
        "low_confidence": 0,
        "no_trades": 0,
        "avg_return": avg_return,
        "avg_drawdown": 1.0,
        "avg_expectancy": avg_expectancy,
        "avg_score": 60.0,
        "holding_utilization_pct": holding_utilization_pct,
        "avg_position_pct": avg_position_pct,
        "target_return_pct": target_return_pct,
    }


def _trade_story(
    symbol: str,
    entry_date: str,
    exit_date: str,
    return_pct: float,
) -> TradeStory:
    return TradeStory(
        symbol=symbol,
        signal_date=entry_date,
        entry_date=entry_date,
        exit_date=exit_date,
        entry_reason="volume_price_trial_entry: node=volume_breakout",
        exit_reason="exit",
        return_pct=return_pct,
        actual_holding_days=3,
        thesis=TradeThesis(
            entry_family="volume_price",
            buy_type="breakout_start",
            vpa_archetype="volume_breakout",
            stage="markup_confirmed",
            expected_holding_days="3-5",
            expected_follow_through="continue higher",
            invalidation_price=9.5,
            take_profit_logic="trail",
            must_hold_conditions=("support holds",),
            must_exit_conditions=("support fails",),
        ),
        confirmations=1,
        warnings=0,
        invalidations=0,
        holding_evidence="support holds",
        verdict="thesis_confirmed",
    )


def _candidate_result(
    *,
    candidate: str,
    tier: str,
    symbol: str,
    loss_attributions: tuple[LossAttribution, ...] = (),
    trade_stories: tuple[TradeStory, ...] = (),
    position_action_reviews: tuple[PositionActionReview, ...] = (),
    knowledge_hypothesis_reviews: tuple[KnowledgeHypothesisReview, ...] = (),
    holding_days: int = 0,
    cash_days: int = 0,
    avg_position_pct: float = 0.0,
    max_position_pct: float = 0.0,
    buy_signal_count: int = 0,
    filtered_buy_signals: int = 0,
    raw_filtered_observations: int = 0,
    ordinary_non_signal_days: int = 0,
    top_filter_reason: str = "-",
    top_filter_count: int = 0,
    filter_attributions: tuple[FilterAttribution, ...] = (),
    missed_big_moves: int = 0,
    missed_big_moves_filtered: int = 0,
    missed_big_moves_ordinary_non_signal: int = 0,
    missed_big_moves_unrecognized: int = 0,
    top_missed_big_move_reason: str = "-",
    missed_opportunity_attributions: tuple[FilterAttribution, ...] = (),
    missed_opportunities: tuple[MissedOpportunity, ...] = (),
    pre_breakout_watch_count: int = 0,
    pre_breakout_confirmed_count: int = 0,
    pre_breakout_handoff_count: int = 0,
    pre_breakout_observations: tuple[PreBreakoutObservation, ...] = (),
    trade_details: tuple[TradeDetail, ...] = (),
) -> CandidateResult:
    return CandidateResult(
        run_id="loss-summary",
        candidate=candidate,
        symbol=symbol,
        skill_lenses=("test",),
        hypothesis="test hypothesis",
        bars_count=120,
        fund_flows_count=120,
        missing_fund_flow_dates=0,
        fills=62,
        closed_round_trips=31,
        sample_quality="medium_confidence",
        final_value=104000.0,
        total_return_pct=4.0,
        max_drawdown_pct=1.0,
        expectancy_pct=0.75,
        account_expectancy_pct=0.03,
        profit_factor=1.8,
        target_conclusion="on_track",
        evidence_score=70.0,
        trading_mode="observe",
        behavior_phase="wait",
        fund_flow_bias="neutral",
        buy_state="wait",
        sell_state="hold",
        candidate_tier=tier,
        holding_days=holding_days,
        cash_days=cash_days,
        avg_position_pct=avg_position_pct,
        max_position_pct=max_position_pct,
        buy_signal_count=buy_signal_count,
        filtered_buy_signals=filtered_buy_signals,
        raw_filtered_observations=raw_filtered_observations,
        ordinary_non_signal_days=ordinary_non_signal_days,
        top_filter_reason=top_filter_reason,
        top_filter_count=top_filter_count,
        filter_attributions=filter_attributions,
        missed_big_moves=missed_big_moves,
        missed_big_moves_filtered=missed_big_moves_filtered,
        missed_big_moves_ordinary_non_signal=missed_big_moves_ordinary_non_signal,
        missed_big_moves_unrecognized=missed_big_moves_unrecognized,
        top_missed_big_move_reason=top_missed_big_move_reason,
        missed_opportunity_attributions=missed_opportunity_attributions,
        missed_opportunities=missed_opportunities,
        pre_breakout_watch_count=pre_breakout_watch_count,
        pre_breakout_confirmed_count=pre_breakout_confirmed_count,
        pre_breakout_handoff_count=pre_breakout_handoff_count,
        pre_breakout_observations=pre_breakout_observations,
        loss_attributions=loss_attributions,
        trade_details=trade_details,
        trade_stories=trade_stories,
        position_action_reviews=position_action_reviews,
        knowledge_hypothesis_reviews=knowledge_hypothesis_reviews,
    )


def _dataset() -> tuple[list[Bar], list[FundFlowSnapshot]]:
    start = date(2026, 1, 1)
    bars = [
        _bar("000001", start + timedelta(days=index), 10.0 + index * 0.03)
        for index in range(75)
    ]
    breakout_date = start + timedelta(days=75)
    failure_date = start + timedelta(days=76)
    exit_date = start + timedelta(days=77)
    bars.extend(
        [
            _bar("000001", breakout_date, 12.4, volume=2_000_000, change_pct=3.0),
            _bar("000001", failure_date, 11.8, volume=3_200_000, change_pct=-4.8),
            _bar("000001", exit_date, 11.7, change_pct=-0.8),
        ]
    )
    flows = [
        _flow(breakout_date, 4_000_000, 2_000_000, -800_000, 9.0, 3.0),
        _flow(failure_date, -4_000_000, -2_000_000, 2_000_000, -9.0, -4.8),
    ]
    return bars, flows


def _bar(
    symbol: str,
    trade_date: date,
    close: float,
    volume: int = 1_000_000,
    change_pct: float = 1.0,
) -> Bar:
    return Bar(
        symbol=symbol,
        trade_date=trade_date,
        open=close,
        high=close,
        low=close * 0.98,
        close=close,
        volume=volume,
        amount=close * volume,
        change_pct=change_pct,
        turnover_rate=5.0,
    )


def _flow(
    trade_date: date,
    super_large: float,
    large: float,
    small: float,
    main_pct: float,
    change_pct: float,
) -> FundFlowSnapshot:
    return FundFlowSnapshot(
        symbol="000001",
        name="test",
        timestamp=datetime.combine(trade_date, datetime.min.time()),
        super_large_net_inflow=super_large,
        large_net_inflow=large,
        medium_net_inflow=0,
        small_net_inflow=small,
        main_net_inflow_pct=main_pct,
        change_pct=change_pct,
        amount=10_000_000,
        turnover_rate=5.0,
        provider="test",
        period="daily",
    )
