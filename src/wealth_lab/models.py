"""Core domain models for the wealth lab."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum


class OrderSide(str, Enum):
    """Supported order directions."""

    BUY = "BUY"
    SELL = "SELL"


class FundSignal(str, Enum):
    """Fund-flow classification shown on the monitor."""

    BUY = "\u4e70\u5165"
    SELL = "\u5356\u51fa"
    DIVERGENCE = "\u5206\u6b67"
    SUSPECTED_DISTRIBUTION = "\u7591\u4f3c\u51fa\u8d27"
    SUSPECTED_ACCUMULATION = "\u7591\u4f3c\u5438\u7b79"
    NONE = "\u65e0\u660e\u663e\u52a8\u4f5c"


class PatternTag(str, Enum):
    """Pattern tags inspired by Wyckoff, O'Neil, Minervini, Livermore, and Darvas."""

    SUSPECTED_ACCUMULATION = "\u7591\u4f3c\u5438\u7b79"
    SUSPECTED_DISTRIBUTION = "\u7591\u4f3c\u6d3e\u53d1"
    VOLUME_BREAKOUT = "\u653e\u91cf\u7a81\u7834"
    PRICE_VOLUME_DIVERGENCE = "\u8d44\u91d1\u4ef7\u683c\u80cc\u79bb"
    VCP_SETUP = "VCP\u84c4\u52bf"
    DARVAS_BOX_BREAKOUT = "\u7bb1\u4f53\u7a81\u7834"
    KEY_POINT_CONFIRMED = "\u5173\u952e\u70b9\u786e\u8ba4"
    FAILED_BREAKOUT = "\u7a81\u7834\u5931\u8d25"
    NO_ACTION = "\u65e0\u660e\u663e\u4e3b\u529b\u52a8\u4f5c"


class AnomalyKind(str, Enum):
    """Intraday anomaly tags used by dashboards and alerts."""

    VOLUME_SPIKE = "\u7a81\u7136\u653e\u91cf"
    BREAKOUT_20D_HIGH = "\u7a81\u7834\u8fd120\u65e5\u9ad8\u70b9"
    SMALL_GAIN_BIG_AMOUNT = "\u6da8\u5e45\u4e0d\u5927\u4f46\u6210\u4ea4\u989d\u653e\u5927"
    NEAR_LIMIT_UP = "\u4e34\u8fd1\u6da8\u505c"
    NEAR_LIMIT_DOWN = "\u4e34\u8fd1\u8dcc\u505c"
    SECTOR_SYNC = "\u677f\u5757\u540c\u6b65\u5f02\u52a8"
    WATCHLIST_DISCIPLINE = "\u81ea\u9009\u80a1\u7eaa\u5f8b\u89e6\u53d1"


@dataclass(frozen=True)
class Bar:
    """One OHLCV bar."""

    symbol: str
    trade_date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    amount: float | None = None
    change_pct: float | None = None
    turnover_rate: float | None = None


@dataclass(frozen=True)
class Quote:
    """A quote snapshot from a data provider."""

    symbol: str
    name: str
    price: float
    change_pct: float | None
    timestamp: datetime
    provider: str
    amount: float | None = None
    volume: int | None = None
    volume_ratio: float | None = None
    turnover_rate: float | None = None
    high_20: float | None = None
    low_20: float | None = None
    sector: str | None = None


@dataclass(frozen=True)
class Order:
    """A simulated order."""

    symbol: str
    side: OrderSide
    quantity: int
    requested_price: float | None = None
    reason: str = ""


@dataclass(frozen=True)
class Fill:
    """A simulated fill."""

    symbol: str
    side: OrderSide
    quantity: int
    price: float
    trade_date: date
    gross_amount: float
    fees: float
    reason: str


@dataclass
class Position:
    """A simulated holding."""

    symbol: str
    quantity: int = 0
    avg_cost: float = 0.0
    last_buy_date: date | None = None

    def market_value(self, price: float) -> float:
        """Return current market value for this position."""

        return self.quantity * price


@dataclass(frozen=True)
class PortfolioSnapshot:
    """Portfolio state at a point in a simulation."""

    trade_date: date
    cash: float
    market_value: float
    total_value: float
    positions: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class StrategySignal:
    """A strategy observation that can be converted to a paper order."""

    symbol: str
    side: OrderSide
    reason: str
    target_weight: float | None = None
    confidence: float = 0.0


@dataclass(frozen=True)
class FundFlowSnapshot:
    """Stock fund-flow snapshot from minute or daily data."""

    symbol: str
    name: str
    timestamp: datetime
    super_large_net_inflow: float
    large_net_inflow: float
    medium_net_inflow: float
    small_net_inflow: float
    main_net_inflow_pct: float | None
    change_pct: float | None
    amount: float | None
    turnover_rate: float | None
    provider: str
    period: str = "today"

    @property
    def main_net_inflow(self) -> float:
        """Return main inflow defined as super-large plus large order inflow."""

        return self.super_large_net_inflow + self.large_net_inflow


@dataclass(frozen=True)
class SectorFundFlowSnapshot:
    """Sector fund-flow snapshot."""

    name: str
    sector_type: str
    timestamp: datetime
    super_large_net_inflow: float
    large_net_inflow: float
    medium_net_inflow: float
    small_net_inflow: float
    main_net_inflow_pct: float | None
    change_pct: float | None
    leading_stock: str | None
    inflow_stock_count: int | None
    provider: str
    period: str = "today"

    @property
    def main_net_inflow(self) -> float:
        """Return main inflow defined as super-large plus large order inflow."""

        return self.super_large_net_inflow + self.large_net_inflow


@dataclass(frozen=True)
class StockSignal:
    """A classified monitor result for one stock."""

    symbol: str
    name: str
    timestamp: datetime
    fund_signal: FundSignal
    pattern_tags: tuple[PatternTag, ...]
    anomalies: tuple[AnomalyKind, ...]
    score: float
    reasons: tuple[str, ...]
    quote: Quote | None
    fund_flow: FundFlowSnapshot
    sector_flow: SectorFundFlowSnapshot | None = None
    intent_profile: MainForceProfile | None = None


@dataclass(frozen=True)
class MainForceProfile:
    """Visible-market proxy profile for possible main-force intent.

    This is an evidence profile, not a claim that the real controlling capital
    position or cost is known.
    """

    trade_date: date
    close: float
    daily_trend: str
    weekly_trend: str
    monthly_trend: str
    stage: str
    vwap_60: float | None
    vwap_120: float | None
    close_vs_vwap_60_pct: float | None
    close_vs_vwap_120_pct: float | None
    turnover_20: float | None
    turnover_60: float | None
    main_flow_3: float | None
    main_flow_5: float | None
    main_flow_10: float | None
    obv_slope_20: float | None
    adl_slope_20: float | None
    accumulation_score: float
    markup_score: float
    distribution_score: float
    evidence: tuple[str, ...] = ()
