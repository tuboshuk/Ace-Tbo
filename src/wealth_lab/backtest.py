"""Backtesting utilities."""

from __future__ import annotations

from dataclasses import dataclass

from wealth_lab.models import Bar, Fill, Order, OrderSide, PortfolioSnapshot
from wealth_lab.paper import PaperBroker
from wealth_lab.rules import round_down_to_lot
from wealth_lab.strategy import MovingAverageStrategy


@dataclass(frozen=True)
class BacktestResult:
    """Summary of one backtest run."""

    initial_cash: float
    final_value: float
    total_return: float
    max_drawdown: float
    fills: list[Fill]
    equity_curve: list[PortfolioSnapshot]
    skipped_signals: list[str]


class BacktestRunner:
    """Run a long-only bar-by-bar backtest."""

    def __init__(
        self,
        bars: list[Bar],
        initial_cash: float = 100000.0,
        strategy: MovingAverageStrategy | None = None,
    ) -> None:
        if not bars:
            raise ValueError("bars must not be empty")
        self.bars = sorted(bars, key=lambda item: (item.trade_date, item.symbol))
        self.initial_cash = initial_cash
        self.strategy = strategy or MovingAverageStrategy()

    def run(self) -> BacktestResult:
        """Execute the configured backtest."""

        broker = PaperBroker(initial_cash=self.initial_cash)
        latest_prices: dict[str, float] = {}
        equity_curve: list[PortfolioSnapshot] = []
        skipped_signals: list[str] = []

        for bar in self.bars:
            latest_prices[bar.symbol] = bar.close
            signal = self.strategy.on_bar(bar, broker)
            if signal is not None:
                order = self._order_from_signal(signal, broker, latest_prices, bar.close)
                if order is not None:
                    try:
                        broker.execute_market_order(order, bar.close, bar.trade_date)
                    except ValueError as exc:
                        skipped_signals.append(f"{bar.trade_date} {bar.symbol}: {exc}")
            equity_curve.append(broker.snapshot(bar.trade_date, latest_prices))

        final_value = equity_curve[-1].total_value
        return BacktestResult(
            initial_cash=self.initial_cash,
            final_value=final_value,
            total_return=(final_value / self.initial_cash) - 1,
            max_drawdown=_max_drawdown([snapshot.total_value for snapshot in equity_curve]),
            fills=list(broker.fills),
            equity_curve=equity_curve,
            skipped_signals=skipped_signals,
        )

    def _order_from_signal(
        self,
        signal,
        broker: PaperBroker,
        latest_prices: dict[str, float],
        price: float,
    ) -> Order | None:
        if signal.side == OrderSide.SELL:
            position = broker.positions.get(signal.symbol)
            if not position or position.quantity <= 0:
                return None
            return Order(
                symbol=signal.symbol,
                side=OrderSide.SELL,
                quantity=position.quantity,
                reason=signal.reason,
            )

        target_weight = signal.target_weight or 0.0
        target_value = broker.equity(latest_prices) * target_weight
        current_position = broker.positions.get(signal.symbol)
        current_value = (
            current_position.quantity * price if current_position is not None else 0.0
        )
        cash_to_deploy = max(0.0, min(broker.cash, target_value - current_value))
        quantity = round_down_to_lot(int(cash_to_deploy / price))
        if quantity <= 0:
            return None
        return Order(
            symbol=signal.symbol,
            side=OrderSide.BUY,
            quantity=quantity,
            reason=signal.reason,
        )


def _max_drawdown(values: list[float]) -> float:
    """Return max drawdown as a positive fraction."""

    peak = values[0]
    worst = 0.0
    for value in values:
        if value > peak:
            peak = value
        drawdown = (peak - value) / peak if peak else 0.0
        worst = max(worst, drawdown)
    return worst

