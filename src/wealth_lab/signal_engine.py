"""Fund-flow, anomaly, and pattern signal engine."""

from __future__ import annotations

from dataclasses import dataclass
from statistics import fmean

from wealth_lab.models import (
    AnomalyKind,
    Bar,
    FundFlowSnapshot,
    FundSignal,
    PatternTag,
    Quote,
    SectorFundFlowSnapshot,
    StockSignal,
)
from wealth_lab.rules import price_limit_pct


@dataclass(frozen=True)
class SignalThresholds:
    """Configurable thresholds for intraday monitoring."""

    main_buy_pct: float = 5.0
    main_sell_pct: float = -5.0
    volume_spike_ratio: float = 2.0
    breakout_volume_ratio: float = 1.5
    mild_price_move_pct: float = 2.0
    high_turnover_rate: float = 8.0
    accumulation_min_volume_ratio: float = 1.1
    accumulation_max_volume_ratio: float = 2.5
    near_limit_buffer_pct: float = 1.0
    near_high_pct: float = 3.0
    low_base_pct: float = 8.0
    require_sector_confirmation: bool = True


class FundSignalEngine:
    """Classify stock fund flow, anomalies, and monitor patterns."""

    def __init__(self, thresholds: SignalThresholds | None = None) -> None:
        self.thresholds = thresholds or SignalThresholds()

    def evaluate(
        self,
        fund_flow: FundFlowSnapshot,
        quote: Quote | None = None,
        sector_flow: SectorFundFlowSnapshot | None = None,
        recent_bars: list[Bar] | None = None,
        discipline_triggered: bool = False,
    ) -> StockSignal:
        """Evaluate one stock and return a classified monitor signal."""

        fund_signal, signal_reasons = self._classify_fund_signal(
            fund_flow,
            quote,
            sector_flow,
        )
        anomalies, anomaly_reasons = self._detect_anomalies(
            fund_flow,
            quote,
            sector_flow,
            discipline_triggered,
        )
        pattern_tags, pattern_reasons = self._detect_patterns(
            fund_flow,
            quote,
            sector_flow,
            recent_bars or [],
        )
        score = self._score(fund_signal, anomalies, pattern_tags, fund_flow)
        return StockSignal(
            symbol=fund_flow.symbol,
            name=fund_flow.name,
            timestamp=fund_flow.timestamp,
            fund_signal=fund_signal,
            pattern_tags=tuple(pattern_tags),
            anomalies=tuple(anomalies),
            score=score,
            reasons=tuple(signal_reasons + anomaly_reasons + pattern_reasons),
            quote=quote,
            fund_flow=fund_flow,
            sector_flow=sector_flow,
        )

    def _classify_fund_signal(
        self,
        fund_flow: FundFlowSnapshot,
        quote: Quote | None,
        sector_flow: SectorFundFlowSnapshot | None,
    ) -> tuple[FundSignal, list[str]]:
        change_pct = _coalesce(fund_flow.change_pct, quote.change_pct if quote else None)
        turnover_rate = _coalesce(
            fund_flow.turnover_rate,
            quote.turnover_rate if quote else None,
        )
        volume_ratio = quote.volume_ratio if quote else None
        main_inflow = fund_flow.main_net_inflow
        main_pct = fund_flow.main_net_inflow_pct
        large_orders = fund_flow.super_large_net_inflow + fund_flow.large_net_inflow
        sector_positive = bool(sector_flow and sector_flow.main_net_inflow > 0)
        sector_confirmed = sector_positive or not self.thresholds.require_sector_confirmation
        amount_expanded = _is_amount_expanded(volume_ratio, self.thresholds)
        high_turnover = bool(
            turnover_rate is not None
            and turnover_rate >= self.thresholds.high_turnover_rate
        )

        if (
            change_pct is not None
            and change_pct > 0
            and main_inflow < 0
            and fund_flow.small_net_inflow > 0
            and large_orders < 0
            and (high_turnover or amount_expanded)
        ):
            return FundSignal.SUSPECTED_DISTRIBUTION, [
                "price up, main flow out, small flow in, turnover/volume expanded"
            ]

        if (
            main_inflow > 0
            and main_pct is not None
            and main_pct >= self.thresholds.main_buy_pct
            and fund_flow.super_large_net_inflow > 0
            and change_pct is not None
            and change_pct > 0
            and amount_expanded
            and sector_confirmed
        ):
            return FundSignal.BUY, [
                "main flow pct, super-large flow, price, and sector flow confirm"
                if sector_positive
                else "main flow pct, super-large flow, price, and volume confirm"
            ]

        if (
            main_inflow < 0
            and fund_flow.super_large_net_inflow < 0
            and (
                (change_pct is not None and change_pct < 0)
                or high_turnover
                or amount_expanded
            )
        ):
            return FundSignal.SELL, [
                "main and super-large flow out with weak price or active turnover"
            ]

        if (
            change_pct is not None
            and abs(change_pct) <= self.thresholds.mild_price_move_pct
            and main_inflow > 0
            and fund_flow.super_large_net_inflow >= 0
            and fund_flow.large_net_inflow >= 0
            and _is_moderate_volume_expansion(volume_ratio, self.thresholds)
        ):
            return FundSignal.SUSPECTED_ACCUMULATION, [
                "mild price move with positive main flow and moderate volume expansion"
            ]

        if _has_divergence(fund_flow, change_pct):
            return FundSignal.DIVERGENCE, [
                "price, main flow, large orders, and small orders diverge"
            ]

        return FundSignal.NONE, ["no fund-flow threshold triggered"]

    def _detect_anomalies(
        self,
        fund_flow: FundFlowSnapshot,
        quote: Quote | None,
        sector_flow: SectorFundFlowSnapshot | None,
        discipline_triggered: bool,
    ) -> tuple[list[AnomalyKind], list[str]]:
        anomalies: list[AnomalyKind] = []
        reasons: list[str] = []
        change_pct = _coalesce(fund_flow.change_pct, quote.change_pct if quote else None)
        volume_ratio = quote.volume_ratio if quote else None

        if volume_ratio is not None and volume_ratio >= self.thresholds.volume_spike_ratio:
            anomalies.append(AnomalyKind.VOLUME_SPIKE)
            reasons.append(f"volume ratio {volume_ratio:.2f} reached spike threshold")

        if quote and quote.high_20 is not None and quote.price >= quote.high_20:
            anomalies.append(AnomalyKind.BREAKOUT_20D_HIGH)
            reasons.append("price broke the recent 20-day high")

        if (
            change_pct is not None
            and 0 <= change_pct <= self.thresholds.mild_price_move_pct
            and volume_ratio is not None
            and volume_ratio >= self.thresholds.volume_spike_ratio
        ):
            anomalies.append(AnomalyKind.SMALL_GAIN_BIG_AMOUNT)
            reasons.append("small price gain with expanded amount/volume")

        if change_pct is not None:
            limit_pct = price_limit_pct(fund_flow.symbol) * 100
            if change_pct >= limit_pct - self.thresholds.near_limit_buffer_pct:
                anomalies.append(AnomalyKind.NEAR_LIMIT_UP)
                reasons.append("change pct is near the board limit-up band")
            if change_pct <= -limit_pct + self.thresholds.near_limit_buffer_pct:
                anomalies.append(AnomalyKind.NEAR_LIMIT_DOWN)
                reasons.append("change pct is near the board limit-down band")

        if sector_flow and sector_flow.main_net_inflow > 0 and fund_flow.main_net_inflow > 0:
            anomalies.append(AnomalyKind.SECTOR_SYNC)
            reasons.append("stock and sector main flows are both positive")

        if discipline_triggered:
            anomalies.append(AnomalyKind.WATCHLIST_DISCIPLINE)
            reasons.append("watchlist discipline condition triggered")

        return anomalies, reasons

    def _detect_patterns(
        self,
        fund_flow: FundFlowSnapshot,
        quote: Quote | None,
        sector_flow: SectorFundFlowSnapshot | None,
        recent_bars: list[Bar],
    ) -> tuple[list[PatternTag], list[str]]:
        tags: list[PatternTag] = []
        reasons: list[str] = []
        change_pct = _coalesce(fund_flow.change_pct, quote.change_pct if quote else None)
        volume_ratio = quote.volume_ratio if quote else None
        sector_positive = bool(sector_flow and sector_flow.main_net_inflow > 0)
        near_high = bool(quote and quote.high_20 and quote.price >= quote.high_20 * 0.97)
        near_low = bool(quote and quote.low_20 and quote.price <= quote.low_20 * 1.08)
        breakout = bool(
            quote
            and quote.high_20 is not None
            and quote.price >= quote.high_20
            and volume_ratio is not None
            and volume_ratio >= self.thresholds.breakout_volume_ratio
        )

        if _wyckoff_accumulation(fund_flow, quote, near_low, self.thresholds):
            tags.append(PatternTag.SUSPECTED_ACCUMULATION)
            reasons.append("Wyckoff-like low base with positive main flow")

        if _wyckoff_distribution(fund_flow, quote, near_high, self.thresholds):
            tags.append(PatternTag.SUSPECTED_DISTRIBUTION)
            reasons.append("Wyckoff-like high base/distribution behavior")

        if breakout and fund_flow.main_net_inflow > 0:
            tags.append(PatternTag.VOLUME_BREAKOUT)
            reasons.append("O'Neil-style volume breakout with positive main flow")
            if sector_positive:
                tags.append(PatternTag.KEY_POINT_CONFIRMED)
                reasons.append("Livermore-style key point confirmed by sector flow")
            if _darvas_box_breakout(quote, recent_bars):
                tags.append(PatternTag.DARVAS_BOX_BREAKOUT)
                reasons.append("Darvas-style box high breakout")

        if _vcp_setup(quote, recent_bars, fund_flow):
            tags.append(PatternTag.VCP_SETUP)
            reasons.append("Minervini-style volatility contraction setup")

        if _has_price_flow_divergence(fund_flow, change_pct):
            tags.append(PatternTag.PRICE_VOLUME_DIVERGENCE)
            reasons.append("fund flow and price action diverge")

        if _failed_breakout(quote, recent_bars, fund_flow):
            tags.append(PatternTag.FAILED_BREAKOUT)
            reasons.append("failed breakout: price fell back under the recent high")

        if not tags:
            tags.append(PatternTag.NO_ACTION)
        return _dedupe_tags(tags), reasons

    def _score(
        self,
        fund_signal: FundSignal,
        anomalies: list[AnomalyKind],
        pattern_tags: list[PatternTag],
        fund_flow: FundFlowSnapshot,
    ) -> float:
        base_scores = {
            FundSignal.BUY: 75.0,
            FundSignal.SELL: 70.0,
            FundSignal.SUSPECTED_DISTRIBUTION: 85.0,
            FundSignal.SUSPECTED_ACCUMULATION: 80.0,
            FundSignal.DIVERGENCE: 60.0,
            FundSignal.NONE: 20.0,
        }
        tag_scores = {
            PatternTag.SUSPECTED_DISTRIBUTION: 12.0,
            PatternTag.SUSPECTED_ACCUMULATION: 10.0,
            PatternTag.VOLUME_BREAKOUT: 12.0,
            PatternTag.DARVAS_BOX_BREAKOUT: 8.0,
            PatternTag.VCP_SETUP: 8.0,
            PatternTag.KEY_POINT_CONFIRMED: 8.0,
            PatternTag.PRICE_VOLUME_DIVERGENCE: 5.0,
            PatternTag.FAILED_BREAKOUT: 10.0,
            PatternTag.NO_ACTION: 0.0,
        }
        main_pct_bonus = min(abs(fund_flow.main_net_inflow_pct or 0), 15.0)
        pattern_bonus = sum(tag_scores[tag] for tag in pattern_tags)
        return min(
            100.0,
            base_scores[fund_signal]
            + len(anomalies) * 3
            + main_pct_bonus
            + pattern_bonus,
        )


def _coalesce(first: float | None, second: float | None) -> float | None:
    return first if first is not None else second


def _is_amount_expanded(
    volume_ratio: float | None,
    thresholds: SignalThresholds,
) -> bool:
    return bool(volume_ratio is not None and volume_ratio >= thresholds.volume_spike_ratio)


def _is_moderate_volume_expansion(
    volume_ratio: float | None,
    thresholds: SignalThresholds,
) -> bool:
    if volume_ratio is None:
        return True
    return (
        thresholds.accumulation_min_volume_ratio
        <= volume_ratio
        <= thresholds.accumulation_max_volume_ratio
    )


def _has_divergence(
    fund_flow: FundFlowSnapshot,
    change_pct: float | None,
) -> bool:
    price_up_main_out = (
        change_pct is not None and change_pct > 0 and fund_flow.main_net_inflow < 0
    )
    price_down_main_in = (
        change_pct is not None and change_pct < 0 and fund_flow.main_net_inflow > 0
    )
    large_small_opposite = fund_flow.main_net_inflow * fund_flow.small_net_inflow < 0
    super_large_opposite = fund_flow.super_large_net_inflow * fund_flow.large_net_inflow < 0
    return (
        price_up_main_out
        or price_down_main_in
        or large_small_opposite
        or super_large_opposite
    )


def _has_price_flow_divergence(
    fund_flow: FundFlowSnapshot,
    change_pct: float | None,
) -> bool:
    price_up_main_out = (
        change_pct is not None and change_pct > 0 and fund_flow.main_net_inflow < 0
    )
    price_down_main_in = (
        change_pct is not None and change_pct < 0 and fund_flow.main_net_inflow > 0
    )
    return price_up_main_out or price_down_main_in


def _wyckoff_accumulation(
    fund_flow: FundFlowSnapshot,
    quote: Quote | None,
    near_low: bool,
    thresholds: SignalThresholds,
) -> bool:
    if quote is None:
        return False
    mild_price = abs(quote.change_pct or 0) <= thresholds.mild_price_move_pct
    moderate_volume = _is_moderate_volume_expansion(quote.volume_ratio, thresholds)
    return (
        near_low
        and mild_price
        and fund_flow.main_net_inflow > 0
        and fund_flow.super_large_net_inflow >= 0
        and moderate_volume
    )


def _wyckoff_distribution(
    fund_flow: FundFlowSnapshot,
    quote: Quote | None,
    near_high: bool,
    thresholds: SignalThresholds,
) -> bool:
    if quote is None:
        return False
    volume_active = _is_amount_expanded(quote.volume_ratio, thresholds)
    high_turnover = bool(
        quote.turnover_rate is not None
        and quote.turnover_rate >= thresholds.high_turnover_rate
    )
    return (
        near_high
        and (volume_active or high_turnover)
        and fund_flow.main_net_inflow < 0
        and fund_flow.super_large_net_inflow < 0
        and fund_flow.small_net_inflow > 0
    )


def _darvas_box_breakout(quote: Quote | None, recent_bars: list[Bar]) -> bool:
    if quote is None or len(recent_bars) < 10:
        return bool(quote and quote.high_20 is not None and quote.price >= quote.high_20)
    highs = [bar.high for bar in recent_bars[-20:]]
    box_high = max(highs)
    return quote.price >= box_high


def _vcp_setup(
    quote: Quote | None,
    recent_bars: list[Bar],
    fund_flow: FundFlowSnapshot,
) -> bool:
    if quote is None:
        return False
    near_high_but_not_breakout = bool(
        quote.high_20 is not None
        and quote.high_20 * 0.95 <= quote.price < quote.high_20
    )
    if len(recent_bars) < 15:
        return near_high_but_not_breakout and fund_flow.main_net_inflow > 0

    first_half = recent_bars[-15:-7]
    second_half = recent_bars[-7:]
    first_range = max(bar.high for bar in first_half) - min(bar.low for bar in first_half)
    second_range = max(bar.high for bar in second_half) - min(bar.low for bar in second_half)
    first_volume = fmean(bar.volume for bar in first_half)
    second_volume = fmean(bar.volume for bar in second_half)
    return (
        near_high_but_not_breakout
        and second_range < first_range
        and second_volume < first_volume
        and fund_flow.main_net_inflow >= 0
    )


def _failed_breakout(
    quote: Quote | None,
    recent_bars: list[Bar],
    fund_flow: FundFlowSnapshot,
) -> bool:
    if quote is None or quote.high_20 is None:
        return False
    broke_recently = bool(recent_bars and max(bar.high for bar in recent_bars[-5:]) >= quote.high_20)
    return (
        broke_recently
        and quote.price < quote.high_20
        and (quote.change_pct or 0) < 0
        and fund_flow.main_net_inflow < 0
    )


def _dedupe_tags(tags: list[PatternTag]) -> list[PatternTag]:
    seen: set[PatternTag] = set()
    result: list[PatternTag] = []
    for tag in tags:
        if tag not in seen:
            seen.add(tag)
            result.append(tag)
    return result
