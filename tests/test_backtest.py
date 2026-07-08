from pathlib import Path

from wealth_lab.backtest import BacktestRunner
from wealth_lab.providers.csv_provider import load_bars
from wealth_lab.strategy import MovingAverageStrategy


def test_demo_backtest_runs() -> None:
    project_root = Path(__file__).resolve().parents[1]
    bars = load_bars(project_root / "data" / "demo_bars.csv")

    result = BacktestRunner(
        bars=bars,
        initial_cash=100000,
        strategy=MovingAverageStrategy(short_window=3, long_window=5),
    ).run()

    assert result.final_value > 0
    assert result.max_drawdown >= 0
    assert len(result.equity_curve) == len(bars)
    assert result.fills

