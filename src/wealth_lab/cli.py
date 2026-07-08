"""Command-line entry points."""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
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
from wealth_lab.providers.csv_provider import load_bars
from wealth_lab.storage import SQLiteRepository
from wealth_lab.strategy import MovingAverageStrategy
from wealth_lab.stock_pool import (
    StockPoolSelection,
    select_nested_random_a_share_pools,
    select_random_a_share_pool,
)
from wealth_lab.training import (
    TrainingRun,
    render_expansion_validation_summary,
    run_replay_training,
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
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "runtime" / "training",
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
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / "runtime" / "training",
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
    elif args.command == "validate-expansion":
        _run_validate_expansion(args)
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
            cache_dir=QUOTE_UNIVERSE_CACHE_DIR,
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
            f"universe_source={selection.universe_source} "
            f"cache={selection.universe_cache_path or '-'}"
        )
        print(f"symbols: {', '.join(symbols)}")
    if not symbols:
        raise SystemExit("train-replay requires symbols or --random-pool-size")
    training_run = run_replay_training(
        symbols=symbols,
        days=args.days,
        initial_cash=args.initial_cash,
        target_annual_return=args.target_annual_return / 100,
        output_dir=args.output_dir,
        pool_source=pool_source,
        pool_seed=pool_seed,
        pool_eligible_symbols=pool_eligible_symbols,
    )
    print(f"training_run: {training_run.run_id}")
    print(f"jsonl: {training_run.jsonl_path}")
    print(f"summary: {training_run.summary_path}")
    print(f"candidate_results: {len(training_run.results)}")
    if training_run.errors:
        print(f"errors: {len(training_run.errors)}")


def _run_validate_expansion(args: argparse.Namespace) -> None:
    selection = select_nested_random_a_share_pools(
        pool_sizes=args.pool_sizes,
        seed=args.random_seed,
        exclude_chinext=not args.include_chinext,
        cache_dir=QUOTE_UNIVERSE_CACHE_DIR,
    )
    print(
        "nested_random_pool: "
        f"sizes={','.join(str(size) for size in selection.requested_sizes)} "
        f"seed={selection.seed} eligible={selection.eligible_count} "
        f"exclude_chinext={selection.exclude_chinext} "
        f"universe_source={selection.universe_source} "
        f"cache={selection.universe_cache_path or '-'}",
        flush=True,
    )
    max_pool = selection.pools[-1]
    print(f"running_pool: size={max_pool.requested_count}", flush=True)
    max_training_run = run_replay_training(
        symbols=list(max_pool.symbols),
        days=args.days,
        initial_cash=args.initial_cash,
        target_annual_return=args.target_annual_return / 100,
        output_dir=args.output_dir,
        pool_source=f"nested_random_{selection.universe_source}",
        pool_seed=max_pool.seed,
        pool_eligible_symbols=max_pool.eligible_count,
        progress_label=f"pool_size={max_pool.requested_count}",
        persist_progress=True,
    )
    runs_by_size = {max_pool.requested_count: max_training_run}
    print(f"summary: {max_training_run.summary_path}", flush=True)
    if max_training_run.missed_report_path:
        print(f"missed_report: {max_training_run.missed_report_path}", flush=True)
    if max_training_run.errors:
        print(f"errors: {len(max_training_run.errors)}", flush=True)

    for pool in selection.pools[:-1]:
        derived_run = _derive_nested_pool_training_run(
            source_run=max_training_run,
            pool=pool,
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


if __name__ == "__main__":
    main()
