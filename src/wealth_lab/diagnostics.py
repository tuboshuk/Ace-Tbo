"""Replay diagnostics for explaining entries, exits, and weak returns."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
import re

from wealth_lab.models import Bar, StockSignal
from wealth_lab.performance import RoundTrip, estimate_returns
from wealth_lab.replay import ReplayDecision, ReplayResult
from wealth_lab.trade_quality import estimate_entry_quality


@dataclass(frozen=True)
class TradeThesis:
    """Pre-trade thesis inferred from the signal-day evidence."""

    entry_family: str
    buy_type: str
    vpa_archetype: str
    stage: str
    expected_holding_days: str
    expected_follow_through: str
    invalidation_price: float | None
    take_profit_logic: str
    must_hold_conditions: tuple[str, ...]
    must_exit_conditions: tuple[str, ...]


@dataclass(frozen=True)
class ThesisCheck:
    """One holding-day check against the original trade thesis."""

    trade_date: str
    day_number: int
    close: float
    change_pct: float | None
    volume_state: str
    main_flow: float | None
    status: str
    notes: tuple[str, ...]


@dataclass(frozen=True)
class TradeStory:
    """Closed trade story: thesis, holding checks, exit, and result."""

    symbol: str
    signal_date: str | None
    entry_date: str
    exit_date: str
    entry_reason: str
    exit_reason: str
    return_pct: float
    actual_holding_days: int
    thesis: TradeThesis
    confirmations: int
    warnings: int
    invalidations: int
    holding_evidence: str
    verdict: str


@dataclass(frozen=True)
class PositionActionReview:
    """Readonly replay review of what the position action could have been."""

    symbol: str
    signal_date: str | None
    entry_date: str
    exit_date: str
    return_pct: float
    gap_pct: float | None
    gap_bucket: int | None
    opening_classification: str
    support_distance_pct: float | None
    position_action: str
    action_reason: str


@dataclass(frozen=True)
class KnowledgeHypothesisReview:
    """Readonly mapping from trade evidence to a knowledge-base hypothesis."""

    symbol: str
    entry_date: str
    source_id: str
    lens: str
    hypothesis_id: str
    bucket: str
    return_pct: float
    verdict: str
    diagnostic_status: str


@dataclass(frozen=True)
class EntryAttribution:
    """One closed trade with its signal-day evidence."""

    entry_family: str
    signal_date: date | None
    entry_date: date
    exit_date: date
    entry_price: float
    exit_price: float
    return_pct: float
    holding_days: int
    entry_reason: str
    exit_reason: str
    detection: str


@dataclass(frozen=True)
class EntryFamilySummary:
    """Aggregate result for one entry family."""

    entry_family: str
    trades: int
    win_rate_pct: float | None
    avg_return_pct: float | None
    total_pnl: float


@dataclass(frozen=True)
class ReplayDiagnostics:
    """High-level diagnosis for a replay result."""

    findings: tuple[str, ...]
    family_summaries: tuple[EntryFamilySummary, ...]
    entries: tuple[EntryAttribution, ...]
    trade_stories: tuple[TradeStory, ...]
    position_action_reviews: tuple[PositionActionReview, ...]
    knowledge_hypothesis_reviews: tuple[KnowledgeHypothesisReview, ...]


def diagnose_replay(result: ReplayResult) -> ReplayDiagnostics:
    """Diagnose why a replay did or did not produce acceptable returns."""

    round_trips, estimate = estimate_returns(result.fills, result.initial_cash)
    entries = tuple(_entry_attribution(result, item) for item in round_trips)
    trade_stories = tuple(_trade_story(result, item) for item in round_trips)
    position_action_reviews = tuple(
        _position_action_review(result, story, _decision_for_entry(result.decisions, trip))
        for story, trip in zip(trade_stories, round_trips)
    )
    knowledge_hypothesis_reviews = tuple(
        _knowledge_hypothesis_reviews(trade_stories, position_action_reviews)
    )
    family_summaries = tuple(_family_summaries(round_trips))
    findings = list(_base_findings(result, estimate.closed_trades, estimate.sample_quality))
    if estimate.expectancy_pct is not None:
        if estimate.expectancy_pct <= 0:
            findings.append(
                f"closed-trade expectancy is negative: {estimate.expectancy_pct:.2f}%"
            )
        else:
            findings.append(
                f"closed-trade expectancy is positive but sample may still be small: {estimate.expectancy_pct:.2f}%"
            )
    worst = _worst_family(family_summaries)
    if worst is not None and worst.avg_return_pct is not None and worst.avg_return_pct < 0:
        findings.append(
            f"weakest entry family is {worst.entry_family}: avg_return={worst.avg_return_pct:.2f}% trades={worst.trades}"
        )
    if result.total_return <= 0:
        findings.append("strategy did not beat cash in this replay; do not promote parameters")
    return ReplayDiagnostics(
        findings=tuple(findings),
        family_summaries=family_summaries,
        entries=entries,
        trade_stories=trade_stories,
        position_action_reviews=position_action_reviews,
        knowledge_hypothesis_reviews=knowledge_hypothesis_reviews,
    )


def _entry_attribution(result: ReplayResult, round_trip: RoundTrip) -> EntryAttribution:
    decision = _decision_for_entry(result.decisions, round_trip)
    signal = _signal_by_date(result, decision.signal_date if decision else None)
    detection = (
        _volume_detection_detail(decision)
        if decision is not None and decision.observation_type == "volume_price"
        else _detection_detail(signal)
    )
    return EntryAttribution(
        entry_family=_entry_family(round_trip.entry_reason),
        signal_date=decision.signal_date if decision else None,
        entry_date=round_trip.entry_date,
        exit_date=round_trip.exit_date,
        entry_price=round_trip.entry_price,
        exit_price=round_trip.exit_price,
        return_pct=round_trip.return_pct,
        holding_days=round_trip.holding_days,
        entry_reason=round_trip.entry_reason,
        exit_reason=round_trip.exit_reason,
        detection=detection,
    )


def _trade_story(result: ReplayResult, round_trip: RoundTrip) -> TradeStory:
    decision = _decision_for_entry(result.decisions, round_trip)
    signal = _signal_by_date(result, decision.signal_date if decision else None)
    thesis = _build_trade_thesis(result, round_trip, decision, signal)
    checks = _thesis_checks(result, round_trip, thesis)
    confirmations = sum(item.status == "confirming" for item in checks)
    warnings = sum(item.status == "warning" for item in checks)
    invalidations = sum(item.status == "invalidated" for item in checks)
    return TradeStory(
        symbol=round_trip.symbol,
        signal_date=decision.signal_date.isoformat() if decision else None,
        entry_date=round_trip.entry_date.isoformat(),
        exit_date=round_trip.exit_date.isoformat(),
        entry_reason=round_trip.entry_reason,
        exit_reason=round_trip.exit_reason,
        return_pct=round(round_trip.return_pct, 4),
        actual_holding_days=round_trip.holding_days,
        thesis=thesis,
        confirmations=confirmations,
        warnings=warnings,
        invalidations=invalidations,
        holding_evidence=_holding_evidence(checks),
        verdict=_story_verdict(round_trip, checks),
    )


def _build_trade_thesis(
    result: ReplayResult,
    round_trip: RoundTrip,
    decision: ReplayDecision | None,
    signal: StockSignal | None,
) -> TradeThesis:
    entry_family = _entry_family(round_trip.entry_reason)
    buy_type = _buy_type(entry_family, round_trip.entry_reason, decision)
    stage = _stage(signal, decision)
    invalidation_price = _invalidation_price(result, round_trip, decision)
    expected_holding_days = _expected_holding_days(buy_type)
    return TradeThesis(
        entry_family=entry_family,
        buy_type=buy_type,
        vpa_archetype=_vpa_archetype(buy_type, decision),
        stage=stage,
        expected_holding_days=expected_holding_days,
        expected_follow_through=_expected_follow_through(buy_type),
        invalidation_price=invalidation_price,
        take_profit_logic=_take_profit_logic(buy_type),
        must_hold_conditions=_must_hold_conditions(buy_type),
        must_exit_conditions=_must_exit_conditions(buy_type),
    )


def _thesis_checks(
    result: ReplayResult,
    round_trip: RoundTrip,
    thesis: TradeThesis,
) -> tuple[ThesisCheck, ...]:
    bars = [
        bar
        for bar in result.bars
        if round_trip.entry_date <= bar.trade_date <= round_trip.exit_date
    ]
    main_flow_by_date = {
        signal.timestamp.date(): signal.fund_flow.main_net_inflow
        for signal in result.signals
    }
    checks: list[ThesisCheck] = []
    for day_number, bar in enumerate(bars, start=1):
        volume_state = _volume_state(result.bars, bar)
        main_flow = main_flow_by_date.get(bar.trade_date)
        status, notes = _check_status(
            bar=bar,
            round_trip=round_trip,
            thesis=thesis,
            volume_state=volume_state,
            main_flow=main_flow,
        )
        checks.append(
            ThesisCheck(
                trade_date=bar.trade_date.isoformat(),
                day_number=day_number,
                close=round(bar.close, 4),
                change_pct=_round_optional(bar.change_pct),
                volume_state=volume_state,
                main_flow=_round_optional(main_flow),
                status=status,
                notes=tuple(notes),
            )
        )
    return tuple(checks)


def _buy_type(
    entry_family: str,
    reason: str,
    decision: ReplayDecision | None,
) -> str:
    reason_lower = reason.lower()
    volume_node = decision.volume_node if decision else None
    if volume_node == "volume_breakout" or "breakout" in reason_lower:
        return "breakout_start"
    if volume_node in {"shrink_pullback", "quiet_consolidation"}:
        return "pullback_or_wash_support"
    if volume_node == "dry_up_base":
        return "dry_up_absorption_test"
    if "proof_probe" in entry_family or "proof_probe" in reason_lower:
        return "disguised_accumulation_probe"
    if "accumulation" in entry_family or "accumulation" in reason_lower:
        return "accumulation_confirmation"
    if "pursuit" in entry_family or "pursuit" in reason_lower:
        return "pursuit_probe"
    return "signal_follow_through_probe"


def _vpa_archetype(buy_type: str, decision: ReplayDecision | None) -> str:
    volume_node = decision.volume_node if decision else None
    if buy_type == "breakout_start":
        return "effort_vs_result_breakout"
    if buy_type == "pullback_or_wash_support":
        if volume_node == "quiet_consolidation":
            return "quiet_consolidation_no_supply_test"
        return "no_supply_pullback_or_wash"
    if buy_type == "dry_up_absorption_test":
        return "dry_up_no_supply_absorption"
    if buy_type == "disguised_accumulation_probe":
        return "apparent_selling_absorption_test"
    if buy_type == "accumulation_confirmation":
        return "accumulation_confirmation_test"
    if buy_type == "pursuit_probe":
        return "attention_chase_follow_through_test"
    return "generic_follow_through_test"


def _stage(signal: StockSignal | None, decision: ReplayDecision | None) -> str:
    if signal is not None and signal.intent_profile is not None:
        return signal.intent_profile.stage
    if decision is not None and decision.volume_node:
        return f"volume_node:{decision.volume_node}"
    return "unknown"


def _invalidation_price(
    result: ReplayResult,
    round_trip: RoundTrip,
    decision: ReplayDecision | None,
) -> float | None:
    support = _support_from_reason(round_trip.entry_reason)
    if support is not None:
        return round(support, 4)
    if decision is not None:
        signal_bar = _bar_by_date(result.bars, decision.signal_date)
        if signal_bar is not None:
            return round(signal_bar.low, 4)
    return round(round_trip.entry_price * 0.97, 4)


def _support_from_reason(reason: str) -> float | None:
    match = re.search(r"support=([0-9]+(?:\.[0-9]+)?)", reason)
    return float(match.group(1)) if match else None


def _expected_holding_days(buy_type: str) -> str:
    if buy_type == "accumulation_confirmation":
        return "5-10 bars"
    if buy_type in {"breakout_start", "disguised_accumulation_probe"}:
        return "3-5 bars"
    if buy_type in {"pullback_or_wash_support", "dry_up_absorption_test"}:
        return "3-5 bars"
    return "1-3 bars"


def _expected_follow_through(buy_type: str) -> str:
    expectations = {
        "breakout_start": (
            "price should hold above the breakout/support area and show demand "
            "within 1-3 bars"
        ),
        "pullback_or_wash_support": (
            "pullback should shrink or stabilize without closing below support"
        ),
        "dry_up_absorption_test": (
            "dry-up should stop falling first, then recover without renewed "
            "distribution"
        ),
        "accumulation_confirmation": (
            "price should stop making lower lows while main flow remains neutral "
            "or improves"
        ),
        "disguised_accumulation_probe": (
            "apparent selling should be followed by support holding and repaired "
            "flow"
        ),
        "pursuit_probe": "strength must continue quickly; hesitation is a warning",
    }
    return expectations.get(
        buy_type,
        "next bars should prove the signal with price stability or follow-through",
    )


def _take_profit_logic(buy_type: str) -> str:
    if buy_type == "breakout_start":
        return "do not sell strength only because it rises; reduce on volume stall or failed retest"
    if buy_type in {"pullback_or_wash_support", "dry_up_absorption_test"}:
        return "hold while support is respected; reduce if bounce stalls with heavy volume"
    return "hold while thesis evidence improves; exit on proof failure or time exhaustion"


def _must_hold_conditions(buy_type: str) -> tuple[str, ...]:
    if buy_type == "breakout_start":
        return (
            "close remains above invalidation/support",
            "follow-through appears within expected window",
            "main flow does not turn into persistent outflow",
        )
    if buy_type in {"pullback_or_wash_support", "dry_up_absorption_test"}:
        return (
            "price does not close below support",
            "selling volume contracts or stabilizes",
            "no high-volume downside break",
        )
    return (
        "price action does not violate invalidation",
        "follow-through does not contradict the original signal",
    )


def _must_exit_conditions(buy_type: str) -> tuple[str, ...]:
    common = (
        "close below invalidation price",
        "high-volume down bar against the thesis",
        "main-force flow turns negative while price weakens",
    )
    if buy_type == "breakout_start":
        return common + ("breakout level is lost after entry",)
    if buy_type in {"pullback_or_wash_support", "dry_up_absorption_test"}:
        return common + ("support bounce fails inside the expected window",)
    return common


def _volume_state(all_bars: list[Bar], bar: Bar) -> str:
    index = next(
        (item_index for item_index, item in enumerate(all_bars) if item.trade_date == bar.trade_date),
        None,
    )
    if index is None or index <= 0:
        return "no_prior_volume"
    previous = all_bars[max(0, index - 5):index]
    avg_volume = sum(item.volume for item in previous) / len(previous)
    ratio = bar.volume / avg_volume if avg_volume else 0.0
    change_pct = bar.change_pct or 0.0
    if ratio >= 1.5 and change_pct <= -2.0:
        return "volume_down_risk"
    if ratio >= 1.8 and change_pct <= 0.5:
        return "high_volume_stall"
    if ratio >= 1.5 and change_pct > 0.5:
        return "volume_confirmation"
    if ratio <= 0.7 and change_pct >= -1.0:
        return "quiet_hold"
    return "normal"


def _check_status(
    *,
    bar: Bar,
    round_trip: RoundTrip,
    thesis: TradeThesis,
    volume_state: str,
    main_flow: float | None,
) -> tuple[str, list[str]]:
    notes: list[str] = []
    invalidation = thesis.invalidation_price
    status = "neutral"
    if invalidation is not None and bar.close < invalidation:
        notes.append("closed_below_invalidation")
        status = "invalidated"
    elif invalidation is not None and bar.low < invalidation:
        notes.append("tested_invalidation_intraday")
        status = "warning"

    change_pct = bar.change_pct or 0.0
    if volume_state in {"volume_down_risk", "high_volume_stall"}:
        notes.append(volume_state)
        status = "warning" if status != "invalidated" else status
    elif volume_state in {"volume_confirmation", "quiet_hold"}:
        notes.append(volume_state)

    if main_flow is not None and main_flow < 0 and change_pct < 0:
        notes.append("flow_out_with_price_weakness")
        status = "warning" if status != "invalidated" else status
    elif main_flow is not None and main_flow >= 0:
        notes.append("main_flow_not_negative")

    if status == "neutral" and bar.close >= round_trip.entry_price:
        notes.append("close_above_entry")
        status = "confirming"
    elif status == "neutral" and volume_state == "quiet_hold":
        notes.append("support_quietly_holding")
        status = "confirming"
    if not notes:
        notes.append("no_clear_confirmation")
    return status, notes


def _holding_evidence(checks: tuple[ThesisCheck, ...]) -> str:
    if not checks:
        return "no holding bars available"
    head = []
    for item in checks[:3]:
        note = ",".join(item.notes[:2])
        head.append(f"d{item.day_number}:{item.status}:{note}")
    if len(checks) > 3:
        head.append(f"...{len(checks)} bars")
    return "; ".join(head)


def _story_verdict(
    round_trip: RoundTrip,
    checks: tuple[ThesisCheck, ...],
) -> str:
    invalidations = sum(item.status == "invalidated" for item in checks)
    warnings = sum(item.status == "warning" for item in checks)
    confirmations = sum(item.status == "confirming" for item in checks)
    if invalidations:
        return "thesis_failed"
    if round_trip.return_pct > 0 and confirmations > warnings:
        return "thesis_confirmed"
    if round_trip.return_pct <= 0 and warnings:
        return "warnings_confirmed_exit"
    if "time" in round_trip.exit_reason.lower() or "scheduled" in round_trip.exit_reason.lower():
        return "time_exit_needs_review"
    return "rule_exit_needs_review"


def _position_action_review(
    result: ReplayResult,
    story: TradeStory,
    decision: ReplayDecision | None,
) -> PositionActionReview:
    gap_pct = _entry_gap_pct(result.bars, story, decision)
    opening_classification = _opening_classification(story.entry_reason, gap_pct)
    support_distance_pct = _support_distance_pct(result.bars, story)
    position_action, action_reason = _position_action(
        story=story,
        opening_classification=opening_classification,
        support_distance_pct=support_distance_pct,
    )
    return PositionActionReview(
        symbol=story.symbol,
        signal_date=story.signal_date,
        entry_date=story.entry_date,
        exit_date=story.exit_date,
        return_pct=story.return_pct,
        gap_pct=_round_optional(gap_pct),
        gap_bucket=_gap_bucket(gap_pct),
        opening_classification=opening_classification,
        support_distance_pct=_round_optional(support_distance_pct),
        position_action=position_action,
        action_reason=action_reason,
    )


def _entry_gap_pct(
    bars: list[Bar],
    story: TradeStory,
    decision: ReplayDecision | None,
) -> float | None:
    if decision is None:
        return None
    signal_bar = _bar_by_date(bars, decision.signal_date)
    entry_bar = _bar_by_date(bars, date.fromisoformat(story.entry_date))
    if signal_bar is None or entry_bar is None or signal_bar.close <= 0:
        return None
    return (entry_bar.open / signal_bar.close - 1) * 100


def _gap_bucket(gap_pct: float | None) -> int | None:
    if gap_pct is None:
        return None
    return int(_clamp(round(gap_pct), -5, 5))


def _opening_classification(reason: str, gap_pct: float | None) -> str:
    match = re.search(r"\bclass=([A-Za-z0-9_]+)", reason)
    if match:
        return match.group(1)
    if gap_pct is None:
        return "insufficient_opening_history"
    rounded_gap = round(gap_pct, 4)
    if rounded_gap > 3.0:
        return "overheated_high_open"
    if rounded_gap < -3.0:
        return "below_expected_open"
    return "neutral_open"


def _support_distance_pct(bars: list[Bar], story: TradeStory) -> float | None:
    entry_bar = _bar_by_date(bars, date.fromisoformat(story.entry_date))
    if entry_bar is None or entry_bar.open <= 0:
        return None
    support = story.thesis.invalidation_price
    if support is None:
        support = _support_from_reason(story.entry_reason)
    if support is None or support <= 0:
        return None
    return (entry_bar.open - support) / entry_bar.open * 100


def _position_action(
    *,
    story: TradeStory,
    opening_classification: str,
    support_distance_pct: float | None,
) -> tuple[str, str]:
    support_ok = _support_distance_reasonable(support_distance_pct)
    if story.invalidations > 0 or story.verdict == "thesis_failed":
        return "exit", "thesis_failed_or_invalidated"
    if opening_classification == "overheated_high_open":
        return "observe", "overheated_high_open"
    if opening_classification == "insufficient_opening_history":
        return "observe", "insufficient_opening_history"
    if not support_ok:
        return "observe", "support_distance_not_usable"
    if story.warnings >= story.confirmations and story.warnings > 0:
        return "reduce", "warnings_not_outweighed_by_confirmations"
    if (
        story.verdict == "thesis_confirmed"
        and story.confirmations >= 2
        and story.warnings == 0
    ):
        if story.confirmations >= 3 and support_distance_pct is not None:
            if support_distance_pct <= 2.0 and story.return_pct >= 3.0:
                return "full_100", "strong_confirmation_replay_suggestion_only"
        return "buy_50", "confirmed_thesis_with_usable_support"
    if opening_classification == "expected_open":
        return "probe_30", "expected_open_with_usable_support"
    return "probe_20", "neutral_usable_review_probe"


def _support_distance_reasonable(value: float | None) -> bool:
    return value is not None and 0.0 < value <= 8.0


def _knowledge_hypothesis_reviews(
    stories: tuple[TradeStory, ...],
    action_reviews: tuple[PositionActionReview, ...],
) -> tuple[KnowledgeHypothesisReview, ...]:
    reviews: list[KnowledgeHypothesisReview] = []
    for story, action_review in zip(stories, action_reviews):
        reviews.extend(
            [
                _knowledge_review(
                    story=story,
                    source_id="coulling_wyckoff_weis",
                    lens="volume_price",
                    hypothesis_id="effort_result_must_confirm_stage",
                    bucket=story.thesis.vpa_archetype,
                ),
                _knowledge_review(
                    story=story,
                    source_id="nison_bulkowski_edwards_magee",
                    lens="pattern_structure",
                    hypothesis_id="pattern_requires_location_and_confirmation",
                    bucket=f"{story.thesis.buy_type}:{_stage_bucket(story.thesis.stage)}",
                ),
                _knowledge_review(
                    story=story,
                    source_id="shannon_livermore",
                    lens="opening_attention",
                    hypothesis_id="opening_gap_changes_risk_reward",
                    bucket=_opening_bucket(action_review),
                ),
                _knowledge_review(
                    story=story,
                    source_id="edwards_magee_livermore",
                    lens="support_risk",
                    hypothesis_id="support_distance_controls_probe_size",
                    bucket=_support_distance_bucket(action_review.support_distance_pct),
                ),
                _knowledge_review(
                    story=story,
                    source_id="oneil_minervini_livermore",
                    lens="invalidation",
                    hypothesis_id="hold_only_while_thesis_is_valid",
                    bucket=_invalidation_bucket(story),
                ),
            ]
        )
    return tuple(reviews)


def _knowledge_review(
    *,
    story: TradeStory,
    source_id: str,
    lens: str,
    hypothesis_id: str,
    bucket: str,
) -> KnowledgeHypothesisReview:
    return KnowledgeHypothesisReview(
        symbol=story.symbol,
        entry_date=story.entry_date,
        source_id=source_id,
        lens=lens,
        hypothesis_id=hypothesis_id,
        bucket=bucket,
        return_pct=story.return_pct,
        verdict=story.verdict,
        diagnostic_status=_knowledge_diagnostic_status(story.verdict),
    )


def _stage_bucket(stage: str) -> str:
    if not stage:
        return "unknown"
    return _safe_bucket(stage)


def _opening_bucket(review: PositionActionReview) -> str:
    bucket = "gap_unknown" if review.gap_bucket is None else f"gap_{review.gap_bucket:+d}"
    return f"{review.opening_classification}:{bucket}"


def _support_distance_bucket(value: float | None) -> str:
    if value is None:
        return "support_unknown"
    if value <= 0:
        return "support_broken_or_zero"
    if value < 0.5:
        return "support_too_close_under_0_5pct"
    if value <= 2.0:
        return "support_tight_0_5_to_2pct"
    if value <= 5.0:
        return "support_wide_2_to_5pct"
    return "support_too_wide_above_5pct"


def _invalidation_bucket(story: TradeStory) -> str:
    if story.invalidations > 0:
        return "invalidated"
    if story.warnings > story.confirmations:
        return "warnings_dominate"
    if story.confirmations > story.warnings:
        return "confirmations_dominate"
    return "mixed_or_no_evidence"


def _knowledge_diagnostic_status(verdict: str) -> str:
    if verdict == "thesis_confirmed":
        return "CONFIRMED_OBSERVATION"
    if verdict == "thesis_failed":
        return "FAILED_OBSERVATION"
    return "OBSERVE_ONLY"


def _safe_bucket(value: object) -> str:
    return str(value).replace("|", "/").replace(" ", "_")


def _family_summaries(round_trips: list[RoundTrip]) -> list[EntryFamilySummary]:
    grouped: dict[str, list[RoundTrip]] = defaultdict(list)
    for item in round_trips:
        grouped[_entry_family(item.entry_reason)].append(item)

    summaries: list[EntryFamilySummary] = []
    for family, items in grouped.items():
        wins = sum(item.net_pnl > 0 for item in items)
        summaries.append(
            EntryFamilySummary(
                entry_family=family,
                trades=len(items),
                win_rate_pct=wins / len(items) * 100 if items else None,
                avg_return_pct=sum(item.return_pct for item in items) / len(items)
                if items
                else None,
                total_pnl=sum(item.net_pnl for item in items),
            )
        )
    return sorted(summaries, key=lambda item: item.total_pnl)


def _base_findings(
    result: ReplayResult,
    closed_trades: int,
    sample_quality: str,
) -> tuple[str, ...]:
    findings: list[str] = []
    coverage = result.fund_flows_count / result.bars_count * 100 if result.bars_count else 0.0
    if coverage < 60:
        findings.append(
            f"fund-flow coverage is low: {coverage:.1f}% ({result.fund_flows_count}/{result.bars_count})"
        )
    if closed_trades < 30:
        findings.append(
            f"closed trades are insufficient for projection: {closed_trades} ({sample_quality})"
        )
    return tuple(findings)


def _decision_for_entry(
    decisions: list[ReplayDecision],
    round_trip: RoundTrip,
) -> ReplayDecision | None:
    candidates = [
        item
        for item in decisions
        if item.side == "BUY"
        and item.signal_date < round_trip.entry_date
        and item.reason == round_trip.entry_reason
    ]
    if candidates:
        return candidates[-1]
    fallback = [
        item
        for item in decisions
        if item.side == "BUY" and item.signal_date < round_trip.entry_date
    ]
    return fallback[-1] if fallback else None


def _signal_by_date(result: ReplayResult, signal_date: date | None):
    if signal_date is None:
        return None
    for signal in result.signals:
        if signal.timestamp.date() == signal_date:
            return signal
    return None


def _bar_by_date(bars: list[Bar], trade_date: date) -> Bar | None:
    for bar in bars:
        if bar.trade_date == trade_date:
            return bar
    return None


def _detection_detail(signal) -> str:
    if signal is None:
        return "signal evidence not found"
    quote = signal.quote
    flow = signal.fund_flow
    profile = signal.intent_profile
    tags = ",".join(tag.value for tag in signal.pattern_tags)
    parts = [
        f"fund_signal={signal.fund_signal.value}",
        f"tags={tags}",
        f"main_flow={flow.main_net_inflow:.0f}",
        f"main_pct={_fmt(flow.main_net_inflow_pct)}%",
        f"super_large={flow.super_large_net_inflow:.0f}",
        f"change={_fmt(flow.change_pct if flow.change_pct is not None else (quote.change_pct if quote else None))}%",
        f"volume_ratio={_fmt(quote.volume_ratio if quote else None)}",
    ]
    quality = estimate_entry_quality(signal, min_reward_risk=1.2)
    parts.extend(
        [
            f"rr={_fmt(quality.reward_risk)}",
            f"risk={_fmt(quality.risk_pct)}%",
            f"support={_fmt(quality.support)}",
            f"target={_fmt(quality.target)}",
            f"quality={quality.reason}",
        ]
    )
    if profile is not None:
        parts.extend(
            [
                f"stage={profile.stage}",
                f"markup={profile.markup_score:.1f}",
                f"acc={profile.accumulation_score:.1f}",
                f"dist={profile.distribution_score:.1f}",
            ]
        )
    return "; ".join(parts)


def _volume_detection_detail(decision: ReplayDecision) -> str:
    return "; ".join(
        [
            f"volume_node={decision.volume_node}",
            f"same_node_cases={decision.volume_probe_cases}",
            f"win_rate={_fmt(decision.volume_probe_win_rate_pct)}%",
            f"avg_return={_fmt(decision.volume_probe_avg_return_pct)}%",
            f"gate_passed={decision.volume_probe_passed}",
            f"reason={decision.reason}",
        ]
    )


def _entry_family(reason: str) -> str:
    return reason.split(":", 1)[0] if ":" in reason else reason


def _worst_family(
    summaries: tuple[EntryFamilySummary, ...],
) -> EntryFamilySummary | None:
    return summaries[0] if summaries else None


def _fmt(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}"


def _round_optional(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(value, high))
