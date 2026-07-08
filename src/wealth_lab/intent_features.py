"""Visible-market proxies for possible main-force intent."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from statistics import fmean

from wealth_lab.models import Bar, FundFlowSnapshot, MainForceProfile


def build_main_force_profile(
    bars: list[Bar],
    fund_flows: list[FundFlowSnapshot],
    index: int,
) -> MainForceProfile:
    """Build a no-future-leakage intent proxy profile for one daily bar."""

    if index < 0 or index >= len(bars):
        raise IndexError("index out of range")
    history = bars[: index + 1]
    current = history[-1]
    flows = [
        flow
        for flow in sorted(fund_flows, key=lambda item: item.timestamp)
        if flow.timestamp.date() <= current.trade_date
    ]

    daily_trend = _daily_trend(history)
    weekly_bars = _resample_weekly(history)
    monthly_bars = _resample_monthly(history)
    weekly_trend = _ma_trend(weekly_bars, fast=10, slow=30)
    monthly_trend = _ma_trend(monthly_bars, fast=3, slow=6)
    vwap_60 = _rolling_vwap(history, 60)
    vwap_120 = _rolling_vwap(history, 120)
    main_flow_3 = _rolling_main_flow(flows, 3)
    main_flow_5 = _rolling_main_flow(flows, 5)
    main_flow_10 = _rolling_main_flow(flows, 10)
    obv_slope_20 = _obv_slope(history, 20)
    adl_slope_20 = _adl_slope(history, 20)
    turnover_20 = _turnover_sum(history, 20)
    turnover_60 = _turnover_sum(history, 60)

    accumulation_score = _accumulation_score(
        current=current,
        daily_trend=daily_trend,
        weekly_trend=weekly_trend,
        vwap_60=vwap_60,
        main_flow_5=main_flow_5,
        main_flow_10=main_flow_10,
        obv_slope_20=obv_slope_20,
        adl_slope_20=adl_slope_20,
    )
    markup_score = _markup_score(
        current=current,
        history=history,
        daily_trend=daily_trend,
        weekly_trend=weekly_trend,
        monthly_trend=monthly_trend,
        vwap_60=vwap_60,
        main_flow_5=main_flow_5,
        obv_slope_20=obv_slope_20,
    )
    distribution_score = _distribution_score(
        current=current,
        history=history,
        main_flow_5=main_flow_5,
        main_flow_10=main_flow_10,
        adl_slope_20=adl_slope_20,
    )
    evidence = _evidence(
        daily_trend=daily_trend,
        weekly_trend=weekly_trend,
        monthly_trend=monthly_trend,
        close=current.close,
        vwap_60=vwap_60,
        vwap_120=vwap_120,
        main_flow_5=main_flow_5,
        main_flow_10=main_flow_10,
        obv_slope_20=obv_slope_20,
        adl_slope_20=adl_slope_20,
        accumulation_score=accumulation_score,
        markup_score=markup_score,
        distribution_score=distribution_score,
    )
    return MainForceProfile(
        trade_date=current.trade_date,
        close=current.close,
        daily_trend=daily_trend,
        weekly_trend=weekly_trend,
        monthly_trend=monthly_trend,
        stage=_stage(daily_trend, weekly_trend, accumulation_score, markup_score, distribution_score),
        vwap_60=vwap_60,
        vwap_120=vwap_120,
        close_vs_vwap_60_pct=_distance_pct(current.close, vwap_60),
        close_vs_vwap_120_pct=_distance_pct(current.close, vwap_120),
        turnover_20=turnover_20,
        turnover_60=turnover_60,
        main_flow_3=main_flow_3,
        main_flow_5=main_flow_5,
        main_flow_10=main_flow_10,
        obv_slope_20=obv_slope_20,
        adl_slope_20=adl_slope_20,
        accumulation_score=accumulation_score,
        markup_score=markup_score,
        distribution_score=distribution_score,
        evidence=evidence,
    )


def _daily_trend(bars: list[Bar]) -> str:
    ma20 = _sma(bars, 20)
    ma60 = _sma(bars, 60)
    close = bars[-1].close
    if ma20 is None:
        return "insufficient"
    if ma60 is not None and close > ma20 > ma60:
        return "up"
    if ma60 is not None and close < ma20 < ma60:
        return "down"
    if close >= ma20:
        return "base_up"
    return "base_down"


def _ma_trend(bars: list[Bar], fast: int, slow: int) -> str:
    fast_ma = _sma(bars, fast)
    slow_ma = _sma(bars, slow)
    if fast_ma is None:
        return "insufficient"
    close = bars[-1].close
    if slow_ma is not None and close > fast_ma > slow_ma:
        return "up"
    if slow_ma is not None and close < fast_ma < slow_ma:
        return "down"
    if close >= fast_ma:
        return "base_up"
    return "base_down"


def _sma(bars: list[Bar], window: int) -> float | None:
    if len(bars) < window:
        return None
    return fmean(bar.close for bar in bars[-window:])


def _rolling_vwap(bars: list[Bar], window: int) -> float | None:
    samples = [bar for bar in bars[-window:] if bar.amount is not None and bar.volume > 0]
    if not samples:
        return None
    amount = sum(bar.amount or 0 for bar in samples)
    volume = sum(bar.volume for bar in samples)
    if volume <= 0:
        return None
    raw = amount / volume
    close = bars[-1].close
    if raw > close * 20:
        raw = raw / 100
    return raw


def _rolling_main_flow(flows: list[FundFlowSnapshot], window: int) -> float | None:
    if not flows:
        return None
    return sum(flow.main_net_inflow for flow in flows[-window:])


def _turnover_sum(bars: list[Bar], window: int) -> float | None:
    samples = [bar.turnover_rate for bar in bars[-window:] if bar.turnover_rate is not None]
    if not samples:
        return None
    return sum(samples)


def _obv_slope(bars: list[Bar], window: int) -> float | None:
    if len(bars) < 2:
        return None
    samples = bars[-window:]
    obv_values = [0.0]
    for previous, current in zip(samples, samples[1:], strict=False):
        if current.close > previous.close:
            obv_values.append(obv_values[-1] + current.volume)
        elif current.close < previous.close:
            obv_values.append(obv_values[-1] - current.volume)
        else:
            obv_values.append(obv_values[-1])
    return _normalized_slope(obv_values)


def _adl_slope(bars: list[Bar], window: int) -> float | None:
    samples = bars[-window:]
    if not samples:
        return None
    values: list[float] = []
    running = 0.0
    for bar in samples:
        spread = bar.high - bar.low
        clv = 0.0 if spread == 0 else ((bar.close - bar.low) - (bar.high - bar.close)) / spread
        running += clv * bar.volume
        values.append(running)
    return _normalized_slope(values)


def _normalized_slope(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    start = values[0]
    end = values[-1]
    scale = max(abs(start), abs(end), 1.0)
    return (end - start) / scale


def _accumulation_score(
    current: Bar,
    daily_trend: str,
    weekly_trend: str,
    vwap_60: float | None,
    main_flow_5: float | None,
    main_flow_10: float | None,
    obv_slope_20: float | None,
    adl_slope_20: float | None,
) -> float:
    score = 0.0
    if daily_trend in {"base_up", "base_down"}:
        score += 20
    if weekly_trend in {"base_up", "base_down", "up"}:
        score += 15
    if vwap_60 is not None and abs(_distance_pct(current.close, vwap_60) or 0) <= 12:
        score += 15
    if main_flow_5 is not None and main_flow_5 > 0:
        score += 20
    if main_flow_10 is not None and main_flow_10 > 0:
        score += 15
    if obv_slope_20 is not None and obv_slope_20 > 0:
        score += 8
    if adl_slope_20 is not None and adl_slope_20 > 0:
        score += 7
    return min(score, 100.0)


def _markup_score(
    current: Bar,
    history: list[Bar],
    daily_trend: str,
    weekly_trend: str,
    monthly_trend: str,
    vwap_60: float | None,
    main_flow_5: float | None,
    obv_slope_20: float | None,
) -> float:
    previous_high = max((bar.high for bar in history[-21:-1]), default=None)
    volume_ratio = _volume_ratio(history, 20)
    score = 0.0
    if daily_trend == "up":
        score += 20
    if weekly_trend == "up":
        score += 25
    if monthly_trend in {"up", "base_up"}:
        score += 10
    if vwap_60 is not None and current.close > vwap_60:
        score += 10
    if previous_high is not None and current.close >= previous_high:
        score += 15
    if volume_ratio is not None and volume_ratio >= 1.5:
        score += 10
    if main_flow_5 is not None and main_flow_5 > 0:
        score += 7
    if obv_slope_20 is not None and obv_slope_20 > 0:
        score += 3
    return min(score, 100.0)


def _distribution_score(
    current: Bar,
    history: list[Bar],
    main_flow_5: float | None,
    main_flow_10: float | None,
    adl_slope_20: float | None,
) -> float:
    high_60 = max((bar.high for bar in history[-60:]), default=current.high)
    volume_ratio = _volume_ratio(history, 20)
    score = 0.0
    if current.close >= high_60 * 0.92:
        score += 20
    if main_flow_5 is not None and main_flow_5 < 0:
        score += 25
    if main_flow_10 is not None and main_flow_10 < 0:
        score += 20
    if volume_ratio is not None and volume_ratio >= 1.5 and (current.change_pct or 0) <= 2:
        score += 15
    if adl_slope_20 is not None and adl_slope_20 < 0:
        score += 20
    return min(score, 100.0)


def _stage(
    daily_trend: str,
    weekly_trend: str,
    accumulation_score: float,
    markup_score: float,
    distribution_score: float,
) -> str:
    if distribution_score >= 70:
        return "distribution_risk"
    if markup_score >= 70 and weekly_trend == "up":
        return "markup_confirmed"
    if accumulation_score >= 60:
        return "accumulation_watch"
    if weekly_trend == "down" and daily_trend in {"down", "base_down"}:
        return "markdown_risk"
    return "neutral"


def _evidence(
    daily_trend: str,
    weekly_trend: str,
    monthly_trend: str,
    close: float,
    vwap_60: float | None,
    vwap_120: float | None,
    main_flow_5: float | None,
    main_flow_10: float | None,
    obv_slope_20: float | None,
    adl_slope_20: float | None,
    accumulation_score: float,
    markup_score: float,
    distribution_score: float,
) -> tuple[str, ...]:
    notes = [
        f"daily={daily_trend}",
        f"weekly={weekly_trend}",
        f"monthly={monthly_trend}",
        f"accumulation_score={accumulation_score:.1f}",
        f"markup_score={markup_score:.1f}",
        f"distribution_score={distribution_score:.1f}",
    ]
    if vwap_60 is not None:
        notes.append(f"close_vs_vwap60={_distance_pct(close, vwap_60):.2f}%")
    if vwap_120 is not None:
        notes.append(f"close_vs_vwap120={_distance_pct(close, vwap_120):.2f}%")
    if main_flow_5 is not None:
        notes.append(f"main_flow_5={main_flow_5:.0f}")
    if main_flow_10 is not None:
        notes.append(f"main_flow_10={main_flow_10:.0f}")
    if obv_slope_20 is not None:
        notes.append(f"obv_slope20={obv_slope_20:.3f}")
    if adl_slope_20 is not None:
        notes.append(f"adl_slope20={adl_slope_20:.3f}")
    return tuple(notes)


def _volume_ratio(bars: list[Bar], window: int) -> float | None:
    if len(bars) < 2:
        return None
    previous = bars[-window - 1 : -1]
    if not previous:
        return None
    average_volume = fmean(bar.volume for bar in previous)
    if average_volume <= 0:
        return None
    return bars[-1].volume / average_volume


def _distance_pct(value: float, base: float | None) -> float | None:
    if base is None or base == 0:
        return None
    return (value / base - 1) * 100


def _resample_weekly(bars: list[Bar]) -> list[Bar]:
    groups: dict[tuple[int, int], list[Bar]] = defaultdict(list)
    for bar in bars:
        iso = bar.trade_date.isocalendar()
        groups[(iso.year, iso.week)].append(bar)
    return [_aggregate(group) for _, group in sorted(groups.items())]


def _resample_monthly(bars: list[Bar]) -> list[Bar]:
    groups: dict[tuple[int, int], list[Bar]] = defaultdict(list)
    for bar in bars:
        groups[(bar.trade_date.year, bar.trade_date.month)].append(bar)
    return [_aggregate(group) for _, group in sorted(groups.items())]


def _aggregate(group: list[Bar]) -> Bar:
    first = group[0]
    last = group[-1]
    return Bar(
        symbol=last.symbol,
        trade_date=last.trade_date,
        open=first.open,
        high=max(bar.high for bar in group),
        low=min(bar.low for bar in group),
        close=last.close,
        volume=sum(bar.volume for bar in group),
        amount=sum((bar.amount or 0) for bar in group),
        change_pct=None,
        turnover_rate=sum((bar.turnover_rate or 0) for bar in group),
    )

