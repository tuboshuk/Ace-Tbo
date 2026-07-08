from datetime import date

from wealth_lab.models import OrderSide
from wealth_lab.rules import (
    Board,
    can_sell_on_date,
    classify_board,
    price_limit_pct,
    validate_lot,
)


def test_board_classification_and_price_limits() -> None:
    assert classify_board("600519") == Board.MAIN
    assert classify_board("300750") == Board.CHINEXT
    assert classify_board("688981") == Board.STAR
    assert classify_board("bj.830799") == Board.BSE

    assert price_limit_pct("600519") == 0.10
    assert price_limit_pct("300750") == 0.20
    assert price_limit_pct("688981") == 0.20
    assert price_limit_pct("830799") == 0.30


def test_lot_rules() -> None:
    assert validate_lot(OrderSide.BUY, 100).ok
    assert not validate_lot(OrderSide.BUY, 101).ok

    assert validate_lot(OrderSide.SELL, 200, position_quantity=250).ok
    assert validate_lot(OrderSide.SELL, 250, position_quantity=250).ok
    assert not validate_lot(OrderSide.SELL, 50, position_quantity=250).ok


def test_t_plus_one_sell_rule() -> None:
    buy_date = date(2026, 1, 2)
    assert not can_sell_on_date(buy_date, buy_date).ok
    assert can_sell_on_date(date(2026, 1, 5), buy_date).ok

