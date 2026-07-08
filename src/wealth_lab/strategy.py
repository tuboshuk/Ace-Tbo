"""Strategy abstractions and example strategies."""

from __future__ import annotations

from collections import defaultdict
from statistics import fmean

from wealth_lab.models import Bar, OrderSide, StrategySignal
from wealth_lab.paper import PaperBroker


class MovingAverageStrategy:
    """A minimal moving-average strategy for framework validation."""

    def __init__(
        self,
        short_window: int = 3,
        long_window: int = 5,
        target_weight: float = 0.20,
        stop_loss_pct: float = 0.08,
    ) -> None:
        if short_window <= 0 or long_window <= 0:
            raise ValueError("windows must be positive")
        if short_window >= long_window:
            raise ValueError("short_window must be smaller than long_window")
        if not 0 < target_weight <= 1:
            raise ValueError("target_weight must be in (0, 1]")
        if not 0 < stop_loss_pct < 1:
            raise ValueError("stop_loss_pct must be in (0, 1)")
        self.short_window = short_window
        self.long_window = long_window
        self.target_weight = target_weight
        self.stop_loss_pct = stop_loss_pct
        self._closes: dict[str, list[float]] = defaultdict(list)

    def on_bar(self, bar: Bar, broker: PaperBroker) -> StrategySignal | None:
        """Process one bar and return a signal if the state changed."""

        closes = self._closes[bar.symbol]
        closes.append(bar.close)
        if len(closes) < self.long_window:
            return None

        position = broker.positions.get(bar.symbol)
        if position and bar.close <= position.avg_cost * (1 - self.stop_loss_pct):
            return StrategySignal(
                symbol=bar.symbol,
                side=OrderSide.SELL,
                reason="stop_loss",
                confidence=0.8,
            )

        short_ma = fmean(closes[-self.short_window :])
        long_ma = fmean(closes[-self.long_window :])
        previous_short = self._previous_average(closes, self.short_window)
        previous_long = self._previous_average(closes, self.long_window)

        has_position = bool(position and position.quantity > 0)
        if not has_position and short_ma > long_ma:
            if previous_short is None or previous_long is None or previous_short <= previous_long:
                return StrategySignal(
                    symbol=bar.symbol,
                    side=OrderSide.BUY,
                    reason="short_ma_cross_above_long_ma",
                    target_weight=self.target_weight,
                    confidence=0.6,
                )

        if has_position and short_ma < long_ma:
            if previous_short is None or previous_long is None or previous_short >= previous_long:
                return StrategySignal(
                    symbol=bar.symbol,
                    side=OrderSide.SELL,
                    reason="short_ma_cross_below_long_ma",
                    confidence=0.6,
                )

        return None

    def _previous_average(self, closes: list[float], window: int) -> float | None:
        if len(closes) <= window:
            return None
        return fmean(closes[-window - 1 : -1])

