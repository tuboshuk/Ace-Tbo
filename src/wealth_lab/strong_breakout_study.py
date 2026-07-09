"""Study whether strong volume-breakout trades replicate across training runs."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from statistics import median


DEFAULT_CANDIDATE = "volume_price_breakout_opening_guard_probe"


@dataclass(frozen=True)
class StrongBreakoutTrade:
    """One trade matching the strongest observed breakout structure."""

    symbol: str
    entry_date: str
    exit_date: str
    return_pct: float
    actual_holding_days: int
    confirmations: int
    warnings: int
    invalidations: int
    exit_reason: str
    verdict: str
    holding_evidence: str


@dataclass(frozen=True)
class StrongBreakoutStudy:
    """Aggregate evidence for strong volume-breakout replication."""

    run_id: str
    source_path: Path
    candidate: str
    candidate_results: int
    trades: tuple[StrongBreakoutTrade, ...]

    @property
    def trade_count(self) -> int:
        return len(self.trades)

    @property
    def traded_symbols(self) -> int:
        return len({trade.symbol for trade in self.trades})

    @property
    def win_count(self) -> int:
        return sum(1 for trade in self.trades if trade.return_pct > 0)

    @property
    def loss_count(self) -> int:
        return sum(1 for trade in self.trades if trade.return_pct <= 0)

    @property
    def win_rate_pct(self) -> float:
        return self.win_count / self.trade_count * 100 if self.trade_count else 0.0

    @property
    def avg_return_pct(self) -> float:
        return _avg([trade.return_pct for trade in self.trades])

    @property
    def median_return_pct(self) -> float:
        if not self.trades:
            return 0.0
        return float(median(trade.return_pct for trade in self.trades))

    @property
    def best_return_pct(self) -> float:
        return max((trade.return_pct for trade in self.trades), default=0.0)

    @property
    def worst_return_pct(self) -> float:
        return min((trade.return_pct for trade in self.trades), default=0.0)

    @property
    def avg_confirmations(self) -> float:
        return _avg([trade.confirmations for trade in self.trades])

    @property
    def avg_warnings(self) -> float:
        return _avg([trade.warnings for trade in self.trades])

    @property
    def avg_invalidations(self) -> float:
        return _avg([trade.invalidations for trade in self.trades])


def build_strong_breakout_study(
    *,
    jsonl_path: Path,
    candidate: str = DEFAULT_CANDIDATE,
) -> StrongBreakoutStudy:
    """Load a training JSONL artifact and extract strong breakout trades."""

    run_id = "-"
    candidate_results = 0
    trades: list[StrongBreakoutTrade] = []
    with jsonl_path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            record = json.loads(line)
            if record.get("kind") == "training_run":
                run_id = str(record.get("run_id") or run_id)
                continue
            if record.get("kind") != "candidate_result":
                continue
            if record.get("candidate") != candidate:
                continue
            candidate_results += 1
            trades.extend(_matching_trades(record))
    return StrongBreakoutStudy(
        run_id=run_id,
        source_path=jsonl_path,
        candidate=candidate,
        candidate_results=candidate_results,
        trades=tuple(trades),
    )


def write_strong_breakout_study_report(
    *,
    study: StrongBreakoutStudy,
    output_dir: Path,
) -> Path:
    """Persist a strong-breakout study report and return its path."""

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{study.run_id}-strong-breakout-study.md"
    output_path.write_text(
        render_strong_breakout_study(study),
        encoding="utf-8",
    )
    return output_path


def render_strong_breakout_study(study: StrongBreakoutStudy) -> str:
    """Render strong-breakout replication evidence as Markdown."""

    lines = [
        "# Strong Breakout Replication Study",
        "",
        "## Scope",
        f"- run_id: {study.run_id}",
        f"- source: {study.source_path}",
        f"- candidate: {study.candidate}",
        "- filter: breakout_start + effort_vs_result_breakout + volume_node:volume_breakout",
        f"- candidate_results_scanned: {study.candidate_results}",
        "",
        "## Aggregate",
        f"- trades: {study.trade_count}",
        f"- traded_symbols: {study.traded_symbols}",
        f"- wins: {study.win_count}",
        f"- losses: {study.loss_count}",
        f"- win_rate_pct: {study.win_rate_pct:.2f}%",
        f"- avg_return_pct: {study.avg_return_pct:.4f}%",
        f"- median_return_pct: {study.median_return_pct:.4f}%",
        f"- best_return_pct: {study.best_return_pct:.4f}%",
        f"- worst_return_pct: {study.worst_return_pct:.4f}%",
        f"- avg_confirmations: {study.avg_confirmations:.2f}",
        f"- avg_warnings: {study.avg_warnings:.2f}",
        f"- avg_invalidations: {study.avg_invalidations:.2f}",
        "",
        "## Account Contribution Estimate",
        "| fixed_weight | gross_account_contribution |",
        "|---:|---:|",
    ]
    for weight in (0.05, 0.10, 0.15, 0.20):
        lines.append(
            f"| {weight * 100:.0f}% | "
            f"{_gross_account_contribution_pct(study.trades, weight):.4f}% |"
        )

    lines.extend(
        [
            "",
            "## Trades",
            (
                "| symbol | entry | exit | return | hold_days | confirmations | "
                "warnings | invalidations | verdict | exit_reason |"
            ),
            "|---|---|---|---:|---:|---:|---:|---:|---|---|",
        ]
    )
    for trade in sorted(
        study.trades,
        key=lambda item: (item.entry_date, item.symbol),
    ):
        lines.append(
            "| "
            f"{trade.symbol} | "
            f"{trade.entry_date} | "
            f"{trade.exit_date} | "
            f"{trade.return_pct:.4f}% | "
            f"{trade.actual_holding_days} | "
            f"{trade.confirmations} | "
            f"{trade.warnings} | "
            f"{trade.invalidations} | "
            f"{trade.verdict} | "
            f"{trade.exit_reason} |"
        )
    if not study.trades:
        lines.append("| - | - | - | 0.0000% | 0 | 0 | 0 | 0 | no_trades | - |")
    return "\n".join(lines)


def _matching_trades(record: dict[str, object]) -> list[StrongBreakoutTrade]:
    stories = record.get("trade_stories")
    if not isinstance(stories, list):
        return []
    trades: list[StrongBreakoutTrade] = []
    for story in stories:
        if not isinstance(story, dict):
            continue
        thesis = story.get("thesis")
        if not isinstance(thesis, dict):
            continue
        if (
            thesis.get("buy_type") != "breakout_start"
            or thesis.get("vpa_archetype") != "effort_vs_result_breakout"
            or thesis.get("stage") != "volume_node:volume_breakout"
        ):
            continue
        trades.append(
            StrongBreakoutTrade(
                symbol=str(story.get("symbol") or record.get("symbol") or "-"),
                entry_date=str(story.get("entry_date") or "-"),
                exit_date=str(story.get("exit_date") or "-"),
                return_pct=float(story.get("return_pct") or 0.0),
                actual_holding_days=int(story.get("actual_holding_days") or 0),
                confirmations=int(story.get("confirmations") or 0),
                warnings=int(story.get("warnings") or 0),
                invalidations=int(story.get("invalidations") or 0),
                exit_reason=str(story.get("exit_reason") or "-"),
                verdict=str(story.get("verdict") or "-"),
                holding_evidence=str(story.get("holding_evidence") or "-"),
            )
        )
    return trades


def _avg(values: list[float | int]) -> float:
    return sum(values) / len(values) if values else 0.0


def _gross_account_contribution_pct(
    trades: tuple[StrongBreakoutTrade, ...],
    weight: float,
) -> float:
    return sum(trade.return_pct * weight for trade in trades)
