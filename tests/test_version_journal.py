from pathlib import Path

import pytest

from wealth_lab.version_journal import (
    JOURNAL_HEADER,
    VersionMetrics,
    VersionTradeBehaviorEntry,
    append_version_entry,
    render_version_entry,
)


def test_render_version_entry_contains_required_behavior_fields() -> None:
    entry = _entry()

    markdown = render_version_entry(entry)

    assert "## 版本 v015 / 动作 015" in markdown
    assert "- 策略候选：volume_price_trial_probe" in markdown
    assert "python run.py train-replay 000620 000001 --days 370" in markdown
    assert "- 股票池：000620, 000001" in markdown
    assert "- 交易笔数：22" in markdown
    assert "- 买入原因：" in markdown
    assert "动态开盘区间内的小仓位试错" in markdown
    assert "- 卖出原因：" in markdown
    assert "固定观察期结束" in markdown
    assert "- 跳过原因：" in markdown
    assert "高于动态预期开盘区间" in markdown
    assert "- 程序当时认为的市场状态：WAIT_SELL_RISK" in markdown
    assert "- 收益/回撤/期望：总收益 0.01%；年化 0.99%；最大回撤 0.07%；每笔期望 0.75%" in markdown
    assert "- 是否达到年化 10.00%：否" in markdown
    assert "- 下一步：拆解 000001 的负期望样本" in markdown


def test_append_version_entry_creates_header_and_appends_entries(tmp_path: Path) -> None:
    journal_path = tmp_path / "version-trade-behavior-log.md"

    append_version_entry(_entry(version="v015"), journal_path)
    append_version_entry(_entry(version="v016", action_id="016"), journal_path)

    content = journal_path.read_text(encoding="utf-8")
    assert content.startswith(JOURNAL_HEADER.rstrip())
    assert content.count("## 版本 v015 / 动作 015") == 1
    assert content.count("## 版本 v016 / 动作 016") == 1


def test_metrics_target_result_can_be_reached_or_uncomputed() -> None:
    reached = VersionMetrics(
        total_return_pct=12.0,
        annual_return_pct=10.0,
        max_drawdown_pct=2.0,
        expectancy_pct=0.8,
    )
    uncomputed = VersionMetrics(
        total_return_pct=None,
        annual_return_pct=None,
        max_drawdown_pct=None,
        expectancy_pct=None,
    )

    assert reached.reached_annual_target is True
    assert uncomputed.reached_annual_target is None
    assert "是否达到年化 10.00%：未计算" in render_version_entry(
        _entry(metrics=uncomputed)
    )


def test_entry_validation_rejects_empty_stock_pool_and_negative_trades() -> None:
    with pytest.raises(ValueError, match="stock_pool"):
        _entry(stock_pool=())

    with pytest.raises(ValueError, match="trade_count"):
        _entry(trade_count=-1)


def _entry(
    *,
    version: str = "v015",
    action_id: str = "015",
    stock_pool: tuple[str, ...] = ("000620", "000001"),
    trade_count: int = 22,
    metrics: VersionMetrics | None = None,
) -> VersionTradeBehaviorEntry:
    return VersionTradeBehaviorEntry(
        version=version,
        action_id=action_id,
        strategy_candidate="volume_price_trial_probe",
        training_command="python run.py train-replay 000620 000001 --days 370",
        stock_pool=stock_pool,
        trade_count=trade_count,
        buy_reasons=("动态开盘区间内的小仓位试错",),
        sell_reasons=("固定观察期结束",),
        skip_reasons=("高于动态预期开盘区间",),
        program_market_state="WAIT_SELL_RISK",
        metrics=metrics
        or VersionMetrics(
            total_return_pct=0.01,
            annual_return_pct=0.99,
            max_drawdown_pct=0.07,
            expectancy_pct=0.75,
        ),
        next_step="拆解 000001 的负期望样本",
        created_at="2026-07-07T08:26:06+00:00",
    )
