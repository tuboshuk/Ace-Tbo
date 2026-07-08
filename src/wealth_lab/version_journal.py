"""Local markdown journal for version-level trade behavior records."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence


DEFAULT_TARGET_ANNUAL_RETURN_PCT = 10.0
DEFAULT_JOURNAL_PATH = Path("docs/version-trade-behavior-log.md")

JOURNAL_HEADER = """# 版本交易行为记录

用途：记录每一版程序在训练时“程序认为自己看到了什么、为什么买、为什么卖、为什么跳过”，方便多 Worker 监督和回顾。

边界：这里只记录研究回放和模拟交易行为，不记录真实资金建议；策略逻辑由策略 Worker 修改，本文件和工具只负责版本行为台账。

## 固定记录模板

- 版本/动作编号：
- 策略候选：
- 训练命令：
- 股票池：
- 交易笔数：
- 买入原因：
- 卖出原因：
- 跳过原因：
- 程序当时认为的市场状态：
- 收益/回撤/期望：
- 是否达到年化 10%：
- 下一步：
"""


@dataclass(frozen=True)
class VersionMetrics:
    """Return, drawdown, and expectancy metrics for one version run."""

    total_return_pct: float | None
    annual_return_pct: float | None
    max_drawdown_pct: float | None
    expectancy_pct: float | None
    target_annual_return_pct: float = DEFAULT_TARGET_ANNUAL_RETURN_PCT

    def __post_init__(self) -> None:
        if self.target_annual_return_pct <= 0:
            raise ValueError("target_annual_return_pct must be positive")

    @property
    def reached_annual_target(self) -> bool | None:
        """Return whether annualized return reached the configured target."""

        if self.annual_return_pct is None:
            return None
        return self.annual_return_pct >= self.target_annual_return_pct


@dataclass(frozen=True)
class VersionTradeBehaviorEntry:
    """One immutable journal entry for a version's simulated trade behavior."""

    version: str
    action_id: str
    strategy_candidate: str
    training_command: str
    stock_pool: tuple[str, ...]
    trade_count: int
    buy_reasons: tuple[str, ...]
    sell_reasons: tuple[str, ...]
    skip_reasons: tuple[str, ...]
    program_market_state: str
    metrics: VersionMetrics
    next_step: str
    created_at: str | None = None
    notes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.version, "version")
        _require_text(self.action_id, "action_id")
        _require_text(self.strategy_candidate, "strategy_candidate")
        _require_text(self.training_command, "training_command")
        _require_text(self.program_market_state, "program_market_state")
        _require_text(self.next_step, "next_step")
        if self.trade_count < 0:
            raise ValueError("trade_count must be non-negative")

        object.__setattr__(self, "stock_pool", _normalize_items(self.stock_pool))
        object.__setattr__(self, "buy_reasons", _normalize_items(self.buy_reasons))
        object.__setattr__(self, "sell_reasons", _normalize_items(self.sell_reasons))
        object.__setattr__(self, "skip_reasons", _normalize_items(self.skip_reasons))
        object.__setattr__(self, "notes", _normalize_items(self.notes))
        if not self.stock_pool:
            raise ValueError("stock_pool must contain at least one symbol")


def render_version_entry(entry: VersionTradeBehaviorEntry) -> str:
    """Render one version trade behavior entry as markdown."""

    created_at = entry.created_at or _utc_now_iso()
    lines = [
        f"## 版本 {entry.version} / 动作 {entry.action_id}",
        "",
        f"- 记录时间：{created_at}",
        f"- 策略候选：{entry.strategy_candidate}",
        "- 训练命令：",
        "```shell",
        entry.training_command,
        "```",
        f"- 股票池：{', '.join(entry.stock_pool)}",
        f"- 交易笔数：{entry.trade_count}",
        "- 买入原因：",
        *_render_items(entry.buy_reasons),
        "- 卖出原因：",
        *_render_items(entry.sell_reasons),
        "- 跳过原因：",
        *_render_items(entry.skip_reasons),
        f"- 程序当时认为的市场状态：{entry.program_market_state}",
        (
            "- 收益/回撤/期望："
            f"总收益 {_format_pct(entry.metrics.total_return_pct)}；"
            f"年化 {_format_pct(entry.metrics.annual_return_pct)}；"
            f"最大回撤 {_format_pct(entry.metrics.max_drawdown_pct)}；"
            f"每笔期望 {_format_pct(entry.metrics.expectancy_pct)}"
        ),
        (
            f"- 是否达到年化 {_format_pct(entry.metrics.target_annual_return_pct)}："
            f"{_format_target_result(entry.metrics.reached_annual_target)}"
        ),
        f"- 下一步：{entry.next_step}",
    ]
    if entry.notes:
        lines.extend(["- 备注：", *_render_items(entry.notes)])
    return "\n".join(lines) + "\n"


def append_version_entry(
    entry: VersionTradeBehaviorEntry,
    path: Path | str = DEFAULT_JOURNAL_PATH,
) -> Path:
    """Append one entry to a local markdown journal and return the path."""

    journal_path = Path(path)
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    prefix = _append_prefix(journal_path)
    with journal_path.open("a", encoding="utf-8") as handle:
        handle.write(prefix)
        handle.write(render_version_entry(entry))
    return journal_path


def _append_prefix(path: Path) -> str:
    if not path.exists() or path.stat().st_size == 0:
        return JOURNAL_HEADER.rstrip() + "\n\n"

    content = path.read_text(encoding="utf-8")
    if content.endswith("\n\n"):
        return ""
    if content.endswith("\n"):
        return "\n"
    return "\n\n"


def _format_pct(value: float | None) -> str:
    if value is None:
        return "未计算"
    return f"{value:.2f}%"


def _format_target_result(value: bool | None) -> str:
    if value is None:
        return "未计算"
    return "是" if value else "否"


def _normalize_items(values: Sequence[str]) -> tuple[str, ...]:
    return tuple(item.strip() for item in values if item.strip())


def _render_items(values: Sequence[str]) -> list[str]:
    items = _normalize_items(values)
    if not items:
        return ["  - 未记录"]
    return [f"  - {item}" for item in items]


def _require_text(value: str, field_name: str) -> None:
    if not value.strip():
        raise ValueError(f"{field_name} must not be empty")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


__all__ = [
    "DEFAULT_JOURNAL_PATH",
    "DEFAULT_TARGET_ANNUAL_RETURN_PCT",
    "JOURNAL_HEADER",
    "VersionMetrics",
    "VersionTradeBehaviorEntry",
    "append_version_entry",
    "render_version_entry",
]
