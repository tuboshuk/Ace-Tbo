"""Paper broker for simulated A-share orders."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from wealth_lab.models import Fill, Order, OrderSide, PortfolioSnapshot, Position
from wealth_lab.rules import can_sell_on_date, validate_lot


@dataclass(frozen=True)
class CostModel:
    """Configurable cost model.

    Defaults are zero because fees and taxes should be verified against the
    current broker and rules before any real-money use.
    """

    commission_rate: float = 0.0
    min_commission: float = 0.0
    stamp_tax_sell_rate: float = 0.0

    def fees_for(self, side: OrderSide, gross_amount: float) -> float:
        """Calculate estimated fees for a simulated fill."""

        commission = gross_amount * self.commission_rate
        if commission > 0 and commission < self.min_commission:
            commission = self.min_commission
        stamp_tax = gross_amount * self.stamp_tax_sell_rate if side == OrderSide.SELL else 0
        return commission + stamp_tax


class PaperBroker:
    """A simple long-only paper broker."""

    def __init__(self, initial_cash: float, costs: CostModel | None = None) -> None:
        if initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        self.cash = initial_cash
        self.costs = costs or CostModel()
        self.positions: dict[str, Position] = {}
        self.fills: list[Fill] = []

    def execute_market_order(self, order: Order, price: float, trade_date: date) -> Fill:
        """Execute a simulated market order at the supplied price."""

        if price <= 0:
            raise ValueError("price must be positive")

        position = self.positions.get(order.symbol, Position(symbol=order.symbol))
        lot_check = validate_lot(order.side, order.quantity, position.quantity)
        if not lot_check.ok:
            raise ValueError(lot_check.reason)

        gross_amount = order.quantity * price
        fees = self.costs.fees_for(order.side, gross_amount)

        if order.side == OrderSide.BUY:
            self._buy(position, order, price, gross_amount, fees, trade_date)
        else:
            self._sell(position, order, gross_amount, fees, trade_date)

        fill = Fill(
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=price,
            trade_date=trade_date,
            gross_amount=gross_amount,
            fees=fees,
            reason=order.reason,
        )
        self.fills.append(fill)
        return fill

    def _buy(
        self,
        position: Position,
        order: Order,
        price: float,
        gross_amount: float,
        fees: float,
        trade_date: date,
    ) -> None:
        total_cost = gross_amount + fees
        if total_cost > self.cash:
            raise ValueError("insufficient cash")

        new_quantity = position.quantity + order.quantity
        new_cost = position.avg_cost * position.quantity + gross_amount
        position.quantity = new_quantity
        position.avg_cost = new_cost / new_quantity
        position.last_buy_date = trade_date
        self.positions[order.symbol] = position
        self.cash -= total_cost

    def _sell(
        self,
        position: Position,
        order: Order,
        gross_amount: float,
        fees: float,
        trade_date: date,
    ) -> None:
        sell_check = can_sell_on_date(trade_date, position.last_buy_date)
        if not sell_check.ok:
            raise ValueError(sell_check.reason)

        position.quantity -= order.quantity
        self.cash += gross_amount - fees
        if position.quantity == 0:
            self.positions.pop(order.symbol, None)
        else:
            self.positions[order.symbol] = position

    def equity(self, latest_prices: dict[str, float]) -> float:
        """Return current total portfolio value."""

        return self.cash + sum(
            position.market_value(latest_prices.get(symbol, position.avg_cost))
            for symbol, position in self.positions.items()
        )

    def snapshot(self, trade_date: date, latest_prices: dict[str, float]) -> PortfolioSnapshot:
        """Return a point-in-time portfolio snapshot."""

        market_value = sum(
            position.market_value(latest_prices.get(symbol, position.avg_cost))
            for symbol, position in self.positions.items()
        )
        return PortfolioSnapshot(
            trade_date=trade_date,
            cash=self.cash,
            market_value=market_value,
            total_value=self.cash + market_value,
            positions={
                symbol: position.quantity
                for symbol, position in sorted(self.positions.items())
            },
        )

