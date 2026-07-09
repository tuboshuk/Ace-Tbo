"""Command-line entry points."""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import date, datetime, timezone
import json
from pathlib import Path

from wealth_lab.accumulation_proof import (
    build_accumulation_proof_report,
    render_accumulation_proof_report,
    write_accumulation_proof_report,
)
from wealth_lab.analysis import analyze_stock_replay, watch_once
from wealth_lab.backtest import BacktestRunner
from wealth_lab.monitor import run_demo_monitor
from wealth_lab.paper_account import (
    PaperAccountGoalModel,
    PortfolioPaperAccountConfig,
    run_portfolio_paper_account,
    run_single_symbol_paper_account,
)
from wealth_lab.providers.csv_provider import load_bars
from wealth_lab.storage import SQLiteRepository
from wealth_lab.strategy import MovingAverageStrategy
from wealth_lab.stock_pool import (
    StockPoolSelection,
    select_nested_random_a_share_pools,
    select_random_a_share_pool,
)
from wealth_lab.strong_breakout_study import (
    DEFAULT_CANDIDATE,
    build_strong_breakout_study,
    write_strong_breakout_study_report,
)
from wealth_lab.training import (
    TrainingRun,
    render_expansion_validation_summary,
    run_replay_training,
    training_candidates_with_fast_failure_probe,
    training_candidates_with_main_force_profile_probe,
    training_candidates_with_watchlist_probe,
    write_large_pool_diagnosis,
    write_training_artifacts,
)
from wealth_lab.trade_discipline import DisciplineConfig, discipline_config_for_mode


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEMO_CSV = PROJECT_ROOT / "data" / "demo_bars.csv"
DEMO_QUOTES_CSV = PROJECT_ROOT / "data" / "demo_quotes.csv"
DEMO_FUND_FLOWS_CSV = PROJECT_ROOT / "data" / "demo_fund_flows.csv"
DEMO_SECTOR_FLOWS_CSV = PROJECT_ROOT / "data" / "demo_sector_flows.csv"
DEFAULT_DB = PROJECT_ROOT / "runtime" / "wealth_lab.sqlite3"
QUOTE_UNIVERSE_CACHE_DIR = PROJECT_ROOT / "runtime" / "quote_universe"
PAPER_ACCOUNT_OUTPUT_DIR = PROJECT_ROOT / "runtime" / "paper_account"
STUDY_OUTPUT_DIR = PROJECT_ROOT / "runtime" / "studies"


def main() -> None:
    """Run the CLI."""

    parser = argparse.ArgumentParser(prog="wealth-lab")
    subparsers = parser.add_subparsers(dest="command", required=True)

    backtest_parser = subparsers.add_parser("backtest-demo")
    backtest_parser.add_argument("--csv", type=Path, default=DEMO_CSV)
    backtest_parser.add_argument("--initial-cash", type=float, default=100000.0)
    backtest_parser.add_argument("--short-window", type=int, default=3)
    backtest_parser.add_argument("--long-window", type=int, default=5)

    init_db_parser = subparsers.add_parser("init-db")
    init_db_parser.add_argument("--db", type=Path, default=DEFAULT_DB)

    load_csv_parser = subparsers.add_parser("load-csv")
    load_csv_parser.add_argument("--csv", type=Path, default=DEMO_CSV)
    load_csv_parser.add_argument("--db", type=Path, default=DEFAULT_DB)

    monitor_parser = subparsers.add_parser("monitor-demo")
    monitor_parser.add_argument("--quotes", type=Path, default=DEMO_QUOTES_CSV)
    monitor_parser.add_argument("--fund-flows", type=Path, default=DEMO_FUND_FLOWS_CSV)
    monitor_parser.add_argument("--sector-flows", type=Path, default=DEMO_SECTOR_FLOWS_CSV)
    monitor_parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    monitor_parser.add_argument("--limit", type=int, default=10)
    monitor_parser.add_argument("--alerts", action="store_true")
    monitor_parser.add_argument("--no-persist", action="store_true")

    analyze_parser = subparsers.add_parser("analyze-stock")
    analyze_parser.add_argument("symbol")
    analyze_parser.add_argument("--days", type=int, default=370)
    analyze_parser.add_argument("--initial-cash", type=float, default=100000.0)
    analyze_parser.add_argument("--target-annual-return", type=float, default=10.0)
    analyze_parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    analyze_parser.add_argument("--no-persist", action="store_true")
    analyze_parser.add_argument(
        "--strategy-mode",
        choices=(
            "baseline",
            "confirmed",
            "proof-probe",
            "active-probe",
            "volume-probe",
        ),
        default="baseline",
    )
    analyze_parser.add_argument("--disable-pursuit-probe", action="store_true")
    analyze_parser.add_argument("--enable-proof-probe", action="store_true")
    analyze_parser.add_argument("--proof-probe-weight", type=float, default=8.0)

    watch_parser = subparsers.add_parser("watch-once")
    watch_parser.add_argument("symbols", nargs="+")
    watch_parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    watch_parser.add_argument("--alerts", action="store_true")
    watch_parser.add_argument("--no-persist", action="store_true")

    training_parser = subparsers.add_parser("train-replay")
    training_parser.add_argument("symbols", nargs="*")
    training_parser.add_argument("--days", type=int, default=370)
    training_parser.add_argument("--initial-cash", type=float, default=100000.0)
    training_parser.add_argument("--target-annual-return", type=float, default=10.0)
    training_parser.add_argument(
        "--random-pool-size",
        type=int,
        default=0,
        help="Randomly select this many A-share symbols before training.",
    )
    training_parser.add_argument(
        "--random-seed",
        type=int,
        default=20260708,
        help="Seed used with --random-pool-size for reproducible pools.",
    )
    training_parser.add_argument(
        "--include-chinext",
        action="store_true",
        help="Allow ChiNext symbols in a random pool. Default excludes 300/301.",
    )
    training_parser.add_argument(
        "--max-price",
        type=float,
        default=None,
        help="Only include random-pool symbols at or below this spot price.",
    )
    training_parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Concurrent symbol workers for replay training.",
    )
    training_parser.add_argument(
        "--use-quote-cache",
        action="store_true",
        help="Use the latest cached quote universe instead of fetching live spot quotes.",
    )
    training_parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "runtime" / "training",
    )
    training_parser.add_argument(
        "--candidate-suite",
        choices=("default", "watchlist", "main-force-profile", "fast-failure"),
        default="default",
        help=(
            "Candidate suite to run. Use fast-failure for baseline, fast cut, "
            "and weak-main-force fast cut only."
        ),
    )
    training_parser.add_argument(
        "--include-watchlist-probe",
        action="store_true",
        help="Deprecated alias for --candidate-suite watchlist.",
    )
    training_parser.add_argument(
        "--include-main-force-profile-probe",
        action="store_true",
        help="Deprecated alias for --candidate-suite main-force-profile.",
    )

    paper_account_parser = subparsers.add_parser("paper-account")
    paper_account_parser.add_argument("symbol")
    paper_account_parser.add_argument("--start", type=_parse_date, required=True)
    paper_account_parser.add_argument("--end", type=_parse_date, default=date.today())
    paper_account_parser.add_argument("--initial-cash", type=float, default=100000.0)
    paper_account_parser.add_argument("--monthly-target-return-pct", type=float, default=8.0)
    paper_account_parser.add_argument("--cost-budget-pct", type=float, default=30.0)
    paper_account_parser.add_argument(
        "--output-dir",
        type=Path,
        default=PAPER_ACCOUNT_OUTPUT_DIR,
    )

    portfolio_account_parser = subparsers.add_parser("portfolio-paper-account")
    portfolio_account_parser.add_argument("symbols", nargs="+")
    portfolio_account_parser.add_argument("--start", type=_parse_date, required=True)
    portfolio_account_parser.add_argument(
        "--end",
        type=_parse_date,
        default=date.today(),
    )
    portfolio_account_parser.add_argument(
        "--initial-cash",
        type=float,
        default=100000.0,
    )
    portfolio_account_parser.add_argument(
        "--monthly-target-return-pct",
        type=float,
        default=8.0,
    )
    portfolio_account_parser.add_argument("--cost-budget-pct", type=float, default=30.0)
    portfolio_account_parser.add_argument("--max-positions", type=int, default=5)
    portfolio_account_parser.add_argument("--min-buy-weight-pct", type=float, default=20.0)
    portfolio_account_parser.add_argument(
        "--max-position-weight-pct",
        type=float,
        default=20.0,
    )
    portfolio_account_parser.add_argument(
        "--output-dir",
        type=Path,
        default=PAPER_ACCOUNT_OUTPUT_DIR,
    )

    strong_breakout_parser = subparsers.add_parser("strong-breakout-study")
    strong_breakout_parser.add_argument("--jsonl", type=Path, required=True)
    strong_breakout_parser.add_argument("--candidate", default=DEFAULT_CANDIDATE)
    strong_breakout_parser.add_argument(
        "--output-dir",
        type=Path,
        default=STUDY_OUTPUT_DIR,
    )

    validation_parser = subparsers.add_parser("validate-expansion")
    validation_parser.add_argument("--pool-sizes", type=int, nargs="+", default=[50, 100, 300])
    validation_parser.add_argument("--days", type=int, default=370)
    validation_parser.add_argument("--initial-cash", type=float, default=100000.0)
    validation_parser.add_argument("--target-annual-return", type=float, default=10.0)
    validation_parser.add_argument(
        "--random-seed",
        type=int,
        default=20260708,
        help="Seed used for one nested random non-ChiNext pool.",
    )
    validation_parser.add_argument(
        "--include-chinext",
        action="store_true",
        help="Allow ChiNext symbols in validation pools. Default excludes 300/301.",
    )
    validation_parser.add_argument(
        "--max-price",
        type=float,
        default=None,
        help="Only include random-pool symbols at or below this spot price.",
    )
    validation_parser.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Concurrent symbol workers for the largest validation pool.",
    )
    validation_parser.add_argument(
        "--use-quote-cache",
        action="store_true",
        help="Use the latest cached quote universe instead of fetching live spot quotes.",
    )
    validation_parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "runtime" / "training",
    )
    validation_parser.add_argument(
        "--candidate-suite",
        choices=("default", "watchlist", "main-force-profile", "fast-failure"),
        default="default",
        help=(
            "Candidate suite to run. Use fast-failure for baseline, fast cut, "
            "and weak-main-force fast cut only."
        ),
    )
    validation_parser.add_argument(
        "--include-watchlist-probe",
        action="store_true",
        help="Deprecated alias for --candidate-suite watchlist.",
    )
    validation_parser.add_argument(
        "--include-main-force-profile-probe",
        action="store_true",
        help="Deprecated alias for --candidate-suite main-force-profile.",
    )

    diagnosis_parser = subparsers.add_parser("large-pool-diagnosis")
    diagnosis_parser.add_argument("--jsonl", type=Path, required=True)
    diagnosis_parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
    )
    diagnosis_parser.add_argument(
        "--baseline-win-rate",
        type=float,
        default=32.56,
        help="Current large-pool baseline win rate used for profile gates.",
    )

    proof_parser = subparsers.add_parser("prove-accumulation")
    proof_parser.add_argument("symbol")
    proof_parser.add_argument("--days", type=int, default=370)
    proof_parser.add_argument("--initial-cash", type=float, default=100000.0)
    proof_parser.add_argument("--horizon", type=int, default=5)
    proof_parser.add_argument("--min-cases", type=int, default=5)
    proof_parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "runtime" / "proofs",
    )
    proof_parser.add_argument("--no-persist", action="store_true")

    args = parser.parse_args()
    if args.command == "backtest-demo":
        _run_backtest_demo(args)
    elif args.command == "init-db":
        repository = SQLiteRepository(args.db)
        repository.initialize()
        print(f"Initialized SQLite database: {args.db}")
    elif args.command == "load-csv":
        bars = load_bars(args.csv)
        repository = SQLiteRepository(args.db)
        repository.upsert_bars(bars)
        print(f"Loaded {len(bars)} bars into {args.db}")
    elif args.command == "monitor-demo":
        _run_monitor_demo(args)
    elif args.command == "analyze-stock":
        _run_analyze_stock(args)
    elif args.command == "watch-once":
        _run_watch_once(args)
    elif args.command == "train-replay":
        _run_train_replay(args)
    elif args.command == "paper-account":
        _run_paper_account(args)
    elif args.command == "portfolio-paper-account":
        _run_portfolio_paper_account(args)
    elif args.command == "strong-breakout-study":
        _run_strong_breakout_study(args)
    elif args.command == "validate-expansion":
        _run_validate_expansion(args)
    elif args.command == "large-pool-diagnosis":
        _run_large_pool_diagnosis(args)
    elif args.command == "prove-accumulation":
        _run_prove_accumulation(args)


def _run_backtest_demo(args: argparse.Namespace) -> None:
    bars = load_bars(args.csv)
    strategy = MovingAverageStrategy(
        short_window=args.short_window,
        long_window=args.long_window,
    )
    result = BacktestRunner(
        bars=bars,
        initial_cash=args.initial_cash,
        strategy=strategy,
    ).run()
    output = {
        "initial_cash": round(result.initial_cash, 2),
        "final_value": round(result.final_value, 2),
        "total_return_pct": round(result.total_return * 100, 2),
        "max_drawdown_pct": round(result.max_drawdown * 100, 2),
        "fills": [
            {
                "date": fill.trade_date.isoformat(),
                "symbol": fill.symbol,
                "side": fill.side.value,
                "quantity": fill.quantity,
                "price": fill.price,
                "reason": fill.reason,
            }
            for fill in result.fills
        ],
        "skipped_signals": result.skipped_signals,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2))


def _run_monitor_demo(args: argparse.Namespace) -> None:
    result = run_demo_monitor(
        quote_csv=args.quotes,
        fund_flow_csv=args.fund_flows,
        sector_flow_csv=args.sector_flows,
        db_path=args.db,
        limit=args.limit,
        persist=not args.no_persist,
    )
    print(result.dashboard_text)
    if args.alerts and result.alert_messages:
        print()
        print("## Alerts")
        for message in result.alert_messages:
            print(f"- {message}")


def _run_analyze_stock(args: argparse.Namespace) -> None:
    _, report_text = analyze_stock_replay(
        symbol=args.symbol,
        days=args.days,
        initial_cash=args.initial_cash,
        target_annual_return=args.target_annual_return / 100,
        db_path=args.db,
        persist=not args.no_persist,
        discipline_config=_discipline_config_from_args(args),
    )
    print(report_text)


def _run_watch_once(args: argparse.Namespace) -> None:
    result = watch_once(
        symbols=args.symbols,
        db_path=args.db,
        persist=not args.no_persist,
    )
    print(result.dashboard_text)
    if args.alerts and result.alert_messages:
        print()
        print("## Alerts")
        for message in result.alert_messages:
            print(f"- {message}")


def _run_train_replay(args: argparse.Namespace) -> None:
    symbols = list(args.symbols)
    pool_source = "manual"
    pool_seed = None
    pool_eligible_symbols = None
    if args.random_pool_size:
        selection = select_random_a_share_pool(
            count=args.random_pool_size,
            seed=args.random_seed,
            exclude_chinext=not args.include_chinext,
            max_price=args.max_price,
            cache_dir=QUOTE_UNIVERSE_CACHE_DIR,
            prefer_cache=args.use_quote_cache,
        )
        symbols = list(selection.symbols)
        pool_source = f"random_{selection.universe_source}"
        pool_seed = selection.seed
        pool_eligible_symbols = selection.eligible_count
        print(
            "random_pool: "
            f"size={len(symbols)} seed={selection.seed} "
            f"eligible={selection.eligible_count} "
            f"exclude_chinext={selection.exclude_chinext} "
            f"max_price={selection.max_price or '-'} "
            f"universe_source={selection.universe_source} "
            f"cache={selection.universe_cache_path or '-'}"
        )
        print(f"symbols: {', '.join(symbols)}")
    if not symbols:
        raise SystemExit("train-replay requires symbols or --random-pool-size")
    candidates = _training_candidates_from_args(args)
    training_run = run_replay_training(
        symbols=symbols,
        days=args.days,
        initial_cash=args.initial_cash,
        target_annual_return=args.target_annual_return / 100,
        output_dir=args.output_dir,
        candidates=candidates,
        pool_source=pool_source,
        pool_seed=pool_seed,
        pool_eligible_symbols=pool_eligible_symbols,
        max_workers=args.workers,
    )
    print(f"training_run: {training_run.run_id}")
    print(f"jsonl: {training_run.jsonl_path}")
    print(f"summary: {training_run.summary_path}")
    print(f"candidate_results: {len(training_run.results)}")
    if training_run.errors:
        print(f"errors: {len(training_run.errors)}")


def _run_paper_account(args: argparse.Namespace) -> None:
    report = run_single_symbol_paper_account(
        symbol=args.symbol,
        start=args.start,
        end=args.end,
        initial_cash=args.initial_cash,
        output_dir=args.output_dir,
        goal_model=PaperAccountGoalModel(
            monthly_target_return_pct=args.monthly_target_return_pct,
            cost_budget_pct=args.cost_budget_pct,
        ),
    )
    print(f"paper_account_run: {report.run_id}")
    print(f"summary: {report.output_path}")
    print(f"strategy: {report.strategy}")
    print(f"initial_cash: {report.initial_cash:.2f}")
    print(f"final_value: {report.final_value:.2f}")
    print(f"total_return_pct: {report.total_return_pct:.4f}%")
    print(f"monthly_rows: {len(report.monthly_rows)}")


def _run_portfolio_paper_account(args: argparse.Namespace) -> None:
    report = run_portfolio_paper_account(
        symbols=list(args.symbols),
        start=args.start,
        end=args.end,
        initial_cash=args.initial_cash,
        output_dir=args.output_dir,
        config=PortfolioPaperAccountConfig(
            max_positions=args.max_positions,
            min_buy_weight=args.min_buy_weight_pct / 100,
            max_position_weight=args.max_position_weight_pct / 100,
        ),
        goal_model=PaperAccountGoalModel(
            monthly_target_return_pct=args.monthly_target_return_pct,
            cost_budget_pct=args.cost_budget_pct,
        ),
    )
    print(f"portfolio_paper_account_run: {report.run_id}")
    print(f"summary: {report.output_path}")
    print(f"strategy: {report.strategy}")
    print(f"symbols: {', '.join(report.symbols)}")
    print(f"initial_cash: {report.initial_cash:.2f}")
    print(f"final_value: {report.final_value:.2f}")
    print(f"total_return_pct: {report.total_return_pct:.4f}%")
    print(f"max_drawdown_pct: {report.max_drawdown_pct:.4f}%")
    print(f"fills: {len(report.fills)}")
    print(f"skipped_orders: {len(report.skipped_orders)}")
    print(f"errors: {len(report.errors)}")


def _run_strong_breakout_study(args: argparse.Namespace) -> None:
    study = build_strong_breakout_study(
        jsonl_path=args.jsonl,
        candidate=args.candidate,
    )
    output_path = write_strong_breakout_study_report(
        study=study,
        output_dir=args.output_dir,
    )
    print(f"strong_breakout_study: {study.run_id}")
    print(f"summary: {output_path}")
    print(f"candidate: {study.candidate}")
    print(f"trades: {study.trade_count}")
    print(f"traded_symbols: {study.traded_symbols}")
    print(f"win_rate_pct: {study.win_rate_pct:.2f}%")
    print(f"avg_return_pct: {study.avg_return_pct:.4f}%")
    print(f"worst_return_pct: {study.worst_return_pct:.4f}%")


def _run_large_pool_diagnosis(args: argparse.Namespace) -> None:
    output_path = write_large_pool_diagnosis(
        jsonl_path=args.jsonl,
        output_dir=args.output_dir,
        baseline_win_rate_pct=args.baseline_win_rate,
    )
    print(f"large_pool_diagnosis: {output_path}")
    print(f"trade_details_csv: {output_path.with_name(f'{args.jsonl.stem}-trade-details.csv')}")
    print(f"trade_details_markdown: {output_path.with_name(f'{args.jsonl.stem}-trade-details.md')}")


def _run_validate_expansion(args: argparse.Namespace) -> None:
    candidates = _training_candidates_from_args(args)
    max_requested_size = max(args.pool_sizes)
    selection = select_nested_random_a_share_pools(
        pool_sizes=args.pool_sizes,
        seed=args.random_seed,
        exclude_chinext=not args.include_chinext,
        max_price=args.max_price,
        cache_dir=QUOTE_UNIVERSE_CACHE_DIR,
        candidate_count=max_requested_size * 3,
        prefer_cache=args.use_quote_cache,
    )
    print(
        "nested_random_pool: "
        f"sizes={','.join(str(size) for size in selection.requested_sizes)} "
        f"candidate_count={len(selection.candidate_symbols)} "
        f"seed={selection.seed} eligible={selection.eligible_count} "
        f"exclude_chinext={selection.exclude_chinext} "
        f"max_price={selection.max_price or '-'} "
        f"universe_source={selection.universe_source} "
        f"cache={selection.universe_cache_path or '-'}",
        flush=True,
    )
    max_pool = selection.pools[-1]
    print(f"running_pool: size={max_pool.requested_count}", flush=True)
    max_training_run = run_replay_training(
        symbols=list(selection.candidate_symbols or max_pool.symbols),
        days=args.days,
        initial_cash=args.initial_cash,
        target_annual_return=args.target_annual_return / 100,
        output_dir=args.output_dir,
        candidates=candidates,
        pool_source=f"validated_nested_random_{selection.universe_source}",
        pool_seed=max_pool.seed,
        pool_eligible_symbols=max_pool.eligible_count,
        progress_label=f"pool_size={max_pool.requested_count}",
        persist_progress=True,
        required_valid_symbols=max_pool.requested_count,
        max_workers=args.workers,
    )
    runs_by_size = {max_pool.requested_count: max_training_run}
    print(f"summary: {max_training_run.summary_path}", flush=True)
    if max_training_run.missed_report_path:
        print(f"missed_report: {max_training_run.missed_report_path}", flush=True)
    if max_training_run.errors:
        print(f"errors: {len(max_training_run.errors)}", flush=True)

    for pool in selection.pools[:-1]:
        validated_pool = replace(
            pool,
            symbols=max_training_run.symbols[:pool.requested_count],
        )
        derived_run = _derive_nested_pool_training_run(
            source_run=max_training_run,
            pool=validated_pool,
            output_dir=args.output_dir,
        )
        write_training_artifacts(derived_run)
        runs_by_size[pool.requested_count] = derived_run
        print(
            f"derived_pool: size={pool.requested_count} "
            f"summary={derived_run.summary_path}",
            flush=True,
        )
        if derived_run.missed_report_path:
            print(f"missed_report: {derived_run.missed_report_path}", flush=True)

    training_runs = [runs_by_size[pool.requested_count] for pool in selection.pools]
    report_text = render_expansion_validation_summary(tuple(training_runs))
    report_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = args.output_dir / f"{report_id}-expansion-validation-summary.md"
    args.output_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report_text, encoding="utf-8")
    print(f"expansion_summary: {report_path}", flush=True)


def _derive_nested_pool_training_run(
    *,
    source_run: TrainingRun,
    pool: StockPoolSelection,
    output_dir: Path,
) -> TrainingRun:
    pool_symbols = set(pool.symbols)
    run_id = f"{source_run.run_id}-pool{pool.requested_count}"
    return TrainingRun(
        run_id=run_id,
        created_at=source_run.created_at,
        symbols=pool.symbols,
        days=source_run.days,
        initial_cash=source_run.initial_cash,
        target_annual_return=source_run.target_annual_return,
        candidates=source_run.candidates,
        results=tuple(
            replace(result, run_id=run_id)
            for result in source_run.results
            if result.symbol in pool_symbols
        ),
        errors=tuple(
            replace(error, run_id=run_id)
            for error in source_run.errors
            if error.symbol in pool_symbols
        ),
        jsonl_path=output_dir / f"{run_id}-training.jsonl",
        summary_path=output_dir / f"{run_id}-summary.md",
        pool_source=f"{source_run.pool_source}_derived_prefix",
        pool_seed=pool.seed,
        pool_eligible_symbols=pool.eligible_count,
        missed_report_path=(
            output_dir / f"{run_id}-missed_breakout_opportunity_report.md"
        ),
        processed_symbols=pool.requested_count,
        is_partial=source_run.is_partial,
    )


def _run_prove_accumulation(args: argparse.Namespace) -> None:
    replay, _ = analyze_stock_replay(
        symbol=args.symbol,
        days=args.days,
        initial_cash=args.initial_cash,
        db_path=None,
        persist=False,
    )
    watch = watch_once(
        symbols=[args.symbol],
        db_path=None,
        persist=False,
    )
    current_signal = watch.signals[0] if watch.signals else None
    report = build_accumulation_proof_report(
        replay=replay,
        current_signal=current_signal,
        horizon=args.horizon,
        min_cases=args.min_cases,
    )
    rendered = render_accumulation_proof_report(report)
    print(rendered)
    if not args.no_persist:
        output_path = write_accumulation_proof_report(
            report=report,
            output_dir=args.output_dir,
            rendered=rendered,
        )
        print()
        print(f"proof: {output_path}")


def _discipline_config_from_args(args: argparse.Namespace) -> DisciplineConfig | None:
    if (
        getattr(args, "strategy_mode", "baseline") == "baseline"
        and
        not getattr(args, "enable_proof_probe", False)
        and not getattr(args, "disable_pursuit_probe", False)
    ):
        return None
    config = discipline_config_for_mode(getattr(args, "strategy_mode", "baseline"))
    if getattr(args, "disable_pursuit_probe", False):
        config = replace(config, enable_pursuit_probe=False)
    if getattr(args, "enable_proof_probe", False):
        config = replace(
            config,
            enable_accumulation_proof_probe=True,
            accumulation_proof_probe_weight=args.proof_probe_weight / 100,
        )
    return config


def _training_candidates_from_args(args: argparse.Namespace):
    candidate_suite = getattr(args, "candidate_suite", "default")
    legacy_watchlist = getattr(args, "include_watchlist_probe", False)
    legacy_main_force = getattr(args, "include_main_force_profile_probe", False)
    legacy_suites = [
        suite
        for enabled, suite in (
            (legacy_watchlist, "watchlist"),
            (legacy_main_force, "main-force-profile"),
        )
        if enabled
    ]
    if len(legacy_suites) > 1:
        raise SystemExit(
            "choose only one research probe: --include-watchlist-probe or "
            "--include-main-force-profile-probe"
        )
    if legacy_suites and candidate_suite != "default":
        raise SystemExit(
            "choose either --candidate-suite or the deprecated include-probe "
            "flags, not both"
        )
    if legacy_suites:
        candidate_suite = legacy_suites[0]
    if candidate_suite == "watchlist":
        return training_candidates_with_watchlist_probe()
    if candidate_suite == "main-force-profile":
        return training_candidates_with_main_force_profile_probe()
    if candidate_suite == "fast-failure":
        return training_candidates_with_fast_failure_probe()
    return None


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(
            f"invalid date {value!r}; expected YYYY-MM-DD"
        ) from exc


if __name__ == "__main__":
    main()
