"""Trade-quality evidence shared by discipline, diagnostics, and reports."""

from __future__ import annotations

from dataclasses import dataclass

from wealth_lab.models import FundSignal, PatternTag, StockSignal


MAX_ENTRY_RISK_PCT = 8.0


@dataclass(frozen=True)
class EntryQuality:
    """Point-in-time reward/risk estimate for an entry-like signal."""

    passed: bool
    known: bool
    reward_risk: float | None
    risk_pct: float | None
    reward_pct: float | None
    support: float | None
    target: float | None
    reason: str


@dataclass(frozen=True)
class ExitPressure:
    """Early exit pressure inferred before hard exit tags appear."""

    triggered: bool
    score: float
    reasons: tuple[str, ...]


def estimate_entry_quality(
    signal: StockSignal,
    min_reward_risk: float,
) -> EntryQuality:
    """Estimate whether the current signal offers acceptable reward/risk.

    The calculation uses only quote fields built from previous bars plus the
    current close. It is descriptive evidence for a replay decision, not a
    forecast of future price movement.
    """

    quote = signal.quote
    if quote is None or quote.price <= 0:
        return _unknown_quality("missing_quote")

    support = _support_price(signal)
    target = _target_price(signal)
    if support is None or target is None:
        return _unknown_quality("missing_support_or_target")
    if support >= quote.price:
        return _failed_quality(
            support=support,
            target=target,
            reason="support_not_below_entry",
        )
    if target <= quote.price:
        return _failed_quality(
            support=support,
            target=target,
            reason="target_not_above_entry",
        )

    risk = quote.price - support
    reward = target - quote.price
    reward_risk = reward / risk if risk > 0 else None
    risk_pct = risk / quote.price * 100
    reward_pct = reward / quote.price * 100
    passed = bool(
        reward_risk is not None
        and reward_risk >= min_reward_risk
        and risk_pct <= MAX_ENTRY_RISK_PCT
    )
    return EntryQuality(
        passed=passed,
        known=True,
        reward_risk=reward_risk,
        risk_pct=risk_pct,
        reward_pct=reward_pct,
        support=support,
        target=target,
        reason=(
            "pass"
            if passed
            else (
                "reward_risk_or_risk_pct_failed: "
                f"reward_risk={reward_risk:.2f} min={min_reward_risk:.2f} "
                f"risk_pct={risk_pct:.2f} max={MAX_ENTRY_RISK_PCT:.2f}"
            )
        ),
    )


def estimate_inferred_exit_pressure(
    signal: StockSignal,
    avg_cost: float | None,
    trigger_score: float = 55.0,
) -> ExitPressure:
    """Infer whether a long position should exit before a hard sell signal."""

    quote = signal.quote
    flow = signal.fund_flow
    profile = signal.intent_profile
    tags = set(signal.pattern_tags)
    score = 0.0
    reasons: list[str] = []

    main_pct = flow.main_net_inflow_pct
    if flow.main_net_inflow < 0:
        score += 18
        reasons.append("main_flow_negative")
    if main_pct is not None and main_pct <= -3.0:
        score += 22
        reasons.append(f"main_pct={main_pct:.2f}%")
    if flow.super_large_net_inflow < 0:
        score += 15
        reasons.append("super_large_negative")
    if quote is not None and quote.change_pct is not None and quote.change_pct < 0:
        score += 12
        reasons.append(f"price_change={quote.change_pct:.2f}%")
    if quote is not None and avg_cost is not None and quote.price < avg_cost:
        score += 10
        reasons.append(f"below_cost={quote.price:.2f}<{avg_cost:.2f}")
    if profile is not None and profile.distribution_score >= 60.0:
        score += 16
        reasons.append(f"distribution_score={profile.distribution_score:.1f}")
    if profile is not None and profile.markup_score < 45.0:
        score += 8
        reasons.append(f"markup_score={profile.markup_score:.1f}")
    if PatternTag.PRICE_VOLUME_DIVERGENCE in tags:
        score += 10
        reasons.append("price_flow_divergence_tag")
    if signal.fund_signal == FundSignal.DIVERGENCE:
        score += 8
        reasons.append("fund_signal_divergence")

    triggered = score >= trigger_score
    return ExitPressure(
        triggered=triggered,
        score=score,
        reasons=tuple(reasons) if reasons else ("no_early_exit_pressure",),
    )


def _support_price(signal: StockSignal) -> float | None:
    quote = signal.quote
    if quote is None:
        return None
    candidates: list[float] = []
    if quote.low_20 is not None and 0 < quote.low_20 < quote.price:
        candidates.append(quote.low_20)
    if (
        quote.high_20 is not None
        and quote.high_20 > 0
        and quote.high_20 <= quote.price
        and PatternTag.VOLUME_BREAKOUT in signal.pattern_tags
    ):
        candidates.append(quote.high_20 * 0.985)
    profile = signal.intent_profile
    if profile is not None:
        for value in (profile.vwap_60, profile.vwap_120):
            if value is not None and 0 < value < quote.price:
                candidates.append(value)
    return max(candidates) if candidates else None


def _target_price(signal: StockSignal) -> float | None:
    quote = signal.quote
    if quote is None or quote.high_20 is None or quote.low_20 is None:
        return None
    box_range = quote.high_20 - quote.low_20
    if box_range <= 0:
        return None
    if quote.price >= quote.high_20:
        return quote.high_20 + box_range * 0.6
    return quote.high_20


def _unknown_quality(reason: str) -> EntryQuality:
    return EntryQuality(
        passed=True,
        known=False,
        reward_risk=None,
        risk_pct=None,
        reward_pct=None,
        support=None,
        target=None,
        reason=reason,
    )


def _failed_quality(
    *,
    support: float | None,
    target: float | None,
    reason: str,
) -> EntryQuality:
    return EntryQuality(
        passed=False,
        known=True,
        reward_risk=None,
        risk_pct=None,
        reward_pct=None,
        support=support,
        target=target,
        reason=reason,
    )
