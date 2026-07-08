from datetime import date

from wealth_lab.models import Fill, OrderSide
from wealth_lab.performance import estimate_returns


def test_estimate_returns_builds_round_trip_expectancy() -> None:
    fills = [
        _fill(OrderSide.BUY, 1000, 10.0, date(2026, 1, 1), "entry"),
        _fill(OrderSide.SELL, 1000, 11.0, date(2026, 1, 3), "exit"),
        _fill(OrderSide.BUY, 1000, 10.0, date(2026, 1, 4), "entry"),
        _fill(OrderSide.SELL, 1000, 9.5, date(2026, 1, 5), "exit"),
    ]

    round_trips, estimate = estimate_returns(fills, initial_cash=100000)

    assert len(round_trips) == 2
    assert estimate.closed_trades == 2
    assert estimate.win_rate_pct == 50
    assert estimate.expectancy_pct == 2.5
    assert estimate.account_expectancy_pct == 0.25
    assert estimate.profit_factor == 2.0
    assert estimate.sample_quality == "too_small_do_not_project"


def _fill(
    side: OrderSide,
    quantity: int,
    price: float,
    trade_date: date,
    reason: str,
) -> Fill:
    return Fill(
        symbol="000001",
        side=side,
        quantity=quantity,
        price=price,
        trade_date=trade_date,
        gross_amount=quantity * price,
        fees=0.0,
        reason=reason,
    )
