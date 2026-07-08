"""A-share trading-rule helpers used by backtests and paper trading."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

from wealth_lab.models import OrderSide


class Board(str, Enum):
    """Simplified A-share board classification."""

    MAIN = "main"
    STAR = "star"
    CHINEXT = "chinext"
    BSE = "bse"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RuleCheck:
    """Result of an order rule validation."""

    ok: bool
    reason: str = ""


def normalize_symbol(symbol: str) -> str:
    """Return a six-digit stock code from common symbol formats."""

    code = symbol.strip().lower()
    for prefix in ("sh.", "sz.", "bj."):
        if code.startswith(prefix):
            code = code[len(prefix) :]
    for suffix in (".sh", ".sz", ".bj"):
        if code.endswith(suffix):
            code = code[: -len(suffix)]
    return code


def classify_board(symbol: str) -> Board:
    """Classify a simplified A-share board from the stock code prefix."""

    code = normalize_symbol(symbol)
    if code.startswith(("688", "689")):
        return Board.STAR
    if code.startswith(("300", "301")):
        return Board.CHINEXT
    if code.startswith(("43", "83", "87", "88", "920")):
        return Board.BSE
    if code.startswith(("000", "001", "002", "003", "600", "601", "603", "605")):
        return Board.MAIN
    return Board.UNKNOWN


def price_limit_pct(symbol: str) -> float:
    """Return the usual daily price limit for a stock code."""

    board = classify_board(symbol)
    if board == Board.BSE:
        return 0.30
    if board in {Board.STAR, Board.CHINEXT}:
        return 0.20
    return 0.10


def round_down_to_lot(quantity: int, lot_size: int = 100) -> int:
    """Round a share quantity down to a board-lot multiple."""

    if quantity <= 0:
        return 0
    return (quantity // lot_size) * lot_size


def validate_lot(
    side: OrderSide,
    quantity: int,
    position_quantity: int = 0,
    lot_size: int = 100,
) -> RuleCheck:
    """Validate basic A-share lot-size rules."""

    if quantity <= 0:
        return RuleCheck(False, "quantity must be positive")
    if side == OrderSide.BUY and quantity % lot_size != 0:
        return RuleCheck(False, "buy quantity must be a 100-share multiple")
    if side == OrderSide.SELL:
        if quantity > position_quantity:
            return RuleCheck(False, "sell quantity exceeds position")
        remaining = position_quantity - quantity
        if quantity % lot_size != 0 and remaining != 0:
            return RuleCheck(
                False,
                "sell odd-lot quantity only when closing the remaining position",
            )
    return RuleCheck(True)


def can_sell_on_date(trade_date: date, last_buy_date: date | None) -> RuleCheck:
    """Return whether a position is sellable under a conservative T+1 rule."""

    if last_buy_date is None:
        return RuleCheck(True)
    if trade_date <= last_buy_date:
        return RuleCheck(False, "T+1 rule blocks selling securities bought today")
    return RuleCheck(True)

