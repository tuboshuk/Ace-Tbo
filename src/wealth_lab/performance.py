"""Performance and return-estimate helpers for replay results."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean

from wealth_lab.models import Fill, OrderSide


@dataclass(frozen=True)
class RoundTrip:
    """One closed FIFO paper-trade round trip."""

    symbol: str
    entry_date: object
    exit_date: object
    quantity: int
    entry_price: float
    exit_price: float
    net_pnl: float
    return_pct: float
    holding_days: int
    entry_reason: str
    exit_reason: str


@dataclass(frozen=True)
class ReturnEstimate:
    """Realized replay estimate of strategy expectancy."""

    closed_trades: int
    sample_quality: str
    win_rate_pct: float | None
    avg_return_pct: float | None
    avg_win_pct: float | None
    avg_loss_pct: float | None
    expectancy_pct: float | None
    account_expectancy_pct: float | None
    profit_factor: float | None
    avg_holding_days: float | None
    best_trade_pct: float | None
    worst_trade_pct: float | None


def build_round_trips(fills: list[Fill]) -> list[RoundTrip]:
    """Build FIFO round trips from fills."""

    open_lots: list[dict[str, object]] = []
    round_trips: list[RoundTrip] = []

    for fill in fills:
        if fill.side == OrderSide.BUY:
            open_lots.append(
                {
                    "fill": fill,
                    "remaining": fill.quantity,
                }
            )
            continue

        remaining_sell = fill.quantity
        while remaining_sell > 0 and open_lots:
            lot = open_lots[0]
            buy = lot["fill"]
            if not isinstance(buy, Fill):
                raise TypeError("open lot fill must be a Fill")
            lot_remaining = int(lot["remaining"])
            matched_quantity = min(remaining_sell, lot_remaining)
            round_trips.append(_round_trip(buy, fill, matched_quantity))

            remaining_sell -= matched_quantity
            lot["remaining"] = lot_remaining - matched_quantity
            if int(lot["remaining"]) <= 0:
                open_lots.pop(0)

    return round_trips


def estimate_returns(
    fills: list[Fill],
    initial_cash: float,
) -> tuple[list[RoundTrip], ReturnEstimate]:
    """Estimate strategy expectancy from closed paper trades.

    This is a descriptive estimate from replay results. It is not a forecast.
    """

    round_trips = build_round_trips(fills)
    if not round_trips:
        return round_trips, ReturnEstimate(
            closed_trades=0,
            sample_quality="no_closed_trades",
            win_rate_pct=None,
            avg_return_pct=None,
            avg_win_pct=None,
            avg_loss_pct=None,
            expectancy_pct=None,
            account_expectancy_pct=None,
            profit_factor=None,
            avg_holding_days=None,
            best_trade_pct=None,
            worst_trade_pct=None,
        )

    returns = [item.return_pct for item in round_trips]
    wins = [item for item in round_trips if item.net_pnl > 0]
    losses = [item for item in round_trips if item.net_pnl < 0]
    gross_profit = sum(item.net_pnl for item in wins)
    gross_loss = abs(sum(item.net_pnl for item in losses))
    expectancy_pct = fmean(returns)
    account_expectancy_pct = (
        fmean(item.net_pnl for item in round_trips) / initial_cash * 100
        if initial_cash > 0
        else None
    )
    return round_trips, ReturnEstimate(
        closed_trades=len(round_trips),
        sample_quality=_sample_quality(len(round_trips)),
        win_rate_pct=len(wins) / len(round_trips) * 100,
        avg_return_pct=expectancy_pct,
        avg_win_pct=fmean(item.return_pct for item in wins) if wins else None,
        avg_loss_pct=fmean(item.return_pct for item in losses) if losses else None,
        expectancy_pct=expectancy_pct,
        account_expectancy_pct=account_expectancy_pct,
        profit_factor=gross_profit / gross_loss if gross_loss > 0 else None,
        avg_holding_days=fmean(item.holding_days for item in round_trips),
        best_trade_pct=max(returns),
        worst_trade_pct=min(returns),
    )


def _round_trip(buy: Fill, sell: Fill, quantity: int) -> RoundTrip:
    buy_fee = buy.fees * quantity / buy.quantity if buy.quantity else 0.0
    sell_fee = sell.fees * quantity / sell.quantity if sell.quantity else 0.0
    entry_gross = buy.price * quantity
    exit_gross = sell.price * quantity
    cost_basis = entry_gross + buy_fee
    net_pnl = exit_gross - entry_gross - buy_fee - sell_fee
    return RoundTrip(
        symbol=buy.symbol,
        entry_date=buy.trade_date,
        exit_date=sell.trade_date,
        quantity=quantity,
        entry_price=buy.price,
        exit_price=sell.price,
        net_pnl=net_pnl,
        return_pct=net_pnl / cost_basis * 100 if cost_basis > 0 else 0.0,
        holding_days=max((sell.trade_date - buy.trade_date).days, 0),
        entry_reason=buy.reason,
        exit_reason=sell.reason,
    )


def _sample_quality(closed_trades: int) -> str:
    if closed_trades < 5:
        return "too_small_do_not_project"
    if closed_trades < 30:
        return "low_confidence"
    if closed_trades < 100:
        return "medium_confidence"
    return "higher_confidence"
