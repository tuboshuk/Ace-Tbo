"""Verification for disguised-accumulation hypotheses."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

from wealth_lab.models import PatternTag, StockSignal

if TYPE_CHECKING:
    from wealth_lab.replay import ReplayResult


@dataclass(frozen=True)
class AccumulationSeed:
    """One apparent selling footprint that may be tested as hidden accumulation."""

    trade_date: str
    symbol: str
    close: float | None
    main_flow: float
    main_pct: float | None
    super_large_flow: float
    large_flow: float
    small_flow: float
    change_pct: float | None
    pattern_tags: tuple[str, ...]
    apparent_selling: bool
    small_order_absorption: bool
    weak_price: bool
    failed_breakout: bool

    @property
    def is_candidate(self) -> bool:
        """Return whether this seed is eligible for accumulation verification."""

        return (
            self.apparent_selling
            and self.small_order_absorption
            and (self.weak_price or self.failed_breakout)
        )


@dataclass(frozen=True)
class ForwardVerification:
    """Forward outcome for one historical seed."""

    seed: AccumulationSeed
    horizon: int
    future_samples: int
    end_date: str | None
    support_return_floor_pct: float | None
    end_return_pct: float | None
    max_rebound_pct: float | None
    future_main_flow: float | None
    support_held: bool | None
    price_recovered: bool | None
    flow_reversed: bool | None
    verdict: str
    evidence: tuple[str, ...]


@dataclass(frozen=True)
class AccumulationProofReport:
    """Historical and current verification report."""

    symbol: str
    horizon: int
    min_cases: int
    current_seed: AccumulationSeed | None
    current_status: str
    current_evidence: tuple[str, ...]
    historical_cases: tuple[ForwardVerification, ...]
    confirmed: int
    failed: int
    inconclusive: int
    confirmation_rate_pct: float | None
    failure_rate_pct: float | None
    conclusion: str


@dataclass(frozen=True)
class AccumulationProofContext:
    """Point-in-time proof context available on one signal date."""

    seed: AccumulationSeed
    historical_cases: int
    confirmed: int
    failed: int
    inconclusive: int
    resolved: int
    confirmation_rate_pct: float | None
    status: str
    evidence: tuple[str, ...]

    @property
    def probe_allowed(self) -> bool:
        """Return whether a small pre-confirmation probe is evidence-supported."""

        return self.status == "history_supported_probe_allowed"


def build_accumulation_proof_report(
    replay: ReplayResult,
    current_signal: StockSignal | None = None,
    horizon: int = 5,
    min_cases: int = 5,
) -> AccumulationProofReport:
    """Build a falsifiable evidence report for hidden accumulation."""

    if horizon <= 0:
        raise ValueError("horizon must be positive")
    if min_cases <= 0:
        raise ValueError("min_cases must be positive")

    historical_cases = tuple(_historical_verifications(replay.signals, horizon))
    confirmed = sum(item.verdict == "confirmed" for item in historical_cases)
    failed = sum(item.verdict == "failed" for item in historical_cases)
    inconclusive = sum(item.verdict == "inconclusive" for item in historical_cases)
    resolved = confirmed + failed
    confirmation_rate = confirmed / resolved * 100 if resolved else None
    failure_rate = failed / resolved * 100 if resolved else None
    current_seed = _seed_from_signal(current_signal) if current_signal else None
    current_status, current_evidence = _current_status(current_seed)

    return AccumulationProofReport(
        symbol=replay.symbol,
        horizon=horizon,
        min_cases=min_cases,
        current_seed=current_seed,
        current_status=current_status,
        current_evidence=current_evidence,
        historical_cases=historical_cases,
        confirmed=confirmed,
        failed=failed,
        inconclusive=inconclusive,
        confirmation_rate_pct=confirmation_rate,
        failure_rate_pct=failure_rate,
        conclusion=_conclusion(
            resolved=resolved,
            confirmed=confirmed,
            failed=failed,
            confirmation_rate=confirmation_rate,
            min_cases=min_cases,
            current_seed=current_seed,
        ),
    )


def build_accumulation_seed(signal: StockSignal) -> AccumulationSeed:
    """Build the observable footprint used by the accumulation verifier."""

    return _seed_from_signal(signal)


def is_disguised_accumulation_candidate(signal: StockSignal) -> bool:
    """Return whether a signal requires disguised-accumulation confirmation."""

    return build_accumulation_seed(signal).is_candidate


def build_point_in_time_proof_context(
    signals: list[StockSignal],
    index: int,
    horizon: int = 5,
    min_cases: int = 5,
    min_confirmation_rate_pct: float = 60.0,
) -> AccumulationProofContext:
    """Build proof context using only cases resolved before ``index``."""

    if not signals:
        raise ValueError("signals must not be empty")
    if index < 0 or index >= len(signals):
        raise ValueError("index out of range")
    if horizon <= 0:
        raise ValueError("horizon must be positive")
    if min_cases <= 0:
        raise ValueError("min_cases must be positive")

    seed = _seed_from_signal(signals[index])
    historical_cases = tuple(
        _resolved_before_index(signals, index, horizon)
    )
    confirmed = sum(item.verdict == "confirmed" for item in historical_cases)
    failed = sum(item.verdict == "failed" for item in historical_cases)
    inconclusive = sum(item.verdict == "inconclusive" for item in historical_cases)
    resolved = confirmed + failed
    confirmation_rate = confirmed / resolved * 100 if resolved else None
    status, evidence = _point_in_time_status(
        seed=seed,
        resolved=resolved,
        confirmation_rate=confirmation_rate,
        min_cases=min_cases,
        min_confirmation_rate_pct=min_confirmation_rate_pct,
    )
    return AccumulationProofContext(
        seed=seed,
        historical_cases=len(historical_cases),
        confirmed=confirmed,
        failed=failed,
        inconclusive=inconclusive,
        resolved=resolved,
        confirmation_rate_pct=confirmation_rate,
        status=status,
        evidence=evidence,
    )


def render_accumulation_proof_report(report: AccumulationProofReport) -> str:
    """Render an accumulation proof report as Markdown."""

    lines = [
        f"# {report.symbol} disguised-accumulation verification",
        "",
        "## Definition",
        "- hypothesis: apparent main-force selling may be hidden accumulation only if later evidence confirms it.",
        "- candidate footprint: main/super-large/large flow out, small orders in, and weak price or failed breakout.",
        f"- confirmation window: next {report.horizon} available signal rows.",
        "- confirmation requires at least two of: support held, price recovered, main flow reversed.",
        "",
        "## Current Signal Test",
    ]
    if report.current_seed is None:
        lines.append("- current_status: no_current_signal")
    else:
        seed = report.current_seed
        lines.extend(
            [
                f"- current_status: {report.current_status}",
                f"- date: {seed.trade_date}",
                f"- close: {_fmt(seed.close)}",
                f"- main_flow: {_money(seed.main_flow)}",
                f"- main_pct: {_pct(seed.main_pct)}",
                f"- super_large_flow: {_money(seed.super_large_flow)}",
                f"- large_flow: {_money(seed.large_flow)}",
                f"- small_flow: {_money(seed.small_flow)}",
                f"- change_pct: {_pct(seed.change_pct)}",
                f"- tags: {','.join(seed.pattern_tags) if seed.pattern_tags else '-'}",
                "",
                "condition | value",
                "--- | ---",
                f"apparent_selling | {seed.apparent_selling}",
                f"small_order_absorption | {seed.small_order_absorption}",
                f"weak_price | {seed.weak_price}",
                f"failed_breakout | {seed.failed_breakout}",
                f"is_candidate | {seed.is_candidate}",
            ]
        )
    lines.extend(f"- {item}" for item in report.current_evidence)

    lines.extend(
        [
            "",
            "## Historical Similar Cases",
            f"- cases: {len(report.historical_cases)}",
            f"- confirmed: {report.confirmed}",
            f"- failed: {report.failed}",
            f"- inconclusive: {report.inconclusive}",
            f"- confirmation_rate_pct: {_pct(report.confirmation_rate_pct)}",
            f"- failure_rate_pct: {_pct(report.failure_rate_pct)}",
            f"- conclusion: {report.conclusion}",
            "",
            "date | close | verdict | end_return | rebound | support_floor | future_flow | evidence",
            "--- | ---: | --- | ---: | ---: | ---: | ---: | ---",
        ]
    )
    if not report.historical_cases:
        lines.append("- | - | no cases | - | - | - | - | -")
    else:
        for item in report.historical_cases[-30:]:
            lines.append(
                " | ".join(
                    [
                        item.seed.trade_date,
                        _fmt(item.seed.close),
                        item.verdict,
                        _pct(item.end_return_pct),
                        _pct(item.max_rebound_pct),
                        _pct(item.support_return_floor_pct),
                        _money(item.future_main_flow),
                        "; ".join(item.evidence),
                    ]
                )
            )
    return "\n".join(lines)


def write_accumulation_proof_report(
    report: AccumulationProofReport,
    output_dir: Path,
    rendered: str | None = None,
    run_time: datetime | None = None,
) -> Path:
    """Write an accumulation proof report and return the Markdown path."""

    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = (run_time or datetime.now(timezone.utc)).strftime("%Y%m%dT%H%M%SZ")
    signal_date = (
        report.current_seed.trade_date
        if report.current_seed is not None
        else "no-current-signal"
    )
    output_path = output_dir / (
        f"{report.symbol}-{signal_date}-h{report.horizon}-{timestamp}.md"
    )
    output_path.write_text(
        rendered if rendered is not None else render_accumulation_proof_report(report),
        encoding="utf-8",
    )
    return output_path


def _historical_verifications(
    signals: list[StockSignal],
    horizon: int,
) -> list[ForwardVerification]:
    verifications: list[ForwardVerification] = []
    for index, signal in enumerate(signals):
        seed = _seed_from_signal(signal)
        if not seed.is_candidate:
            continue
        future = signals[index + 1 : index + 1 + horizon]
        verifications.append(_verify_forward(seed, future, horizon))
    return verifications


def _resolved_before_index(
    signals: list[StockSignal],
    index: int,
    horizon: int,
) -> list[ForwardVerification]:
    verifications: list[ForwardVerification] = []
    for candidate_index in range(index):
        if candidate_index + horizon > index:
            continue
        seed = _seed_from_signal(signals[candidate_index])
        if not seed.is_candidate:
            continue
        future = signals[candidate_index + 1 : candidate_index + 1 + horizon]
        verifications.append(_verify_forward(seed, future, horizon))
    return verifications


def _verify_forward(
    seed: AccumulationSeed,
    future: list[StockSignal],
    horizon: int,
) -> ForwardVerification:
    if seed.close is None or not future:
        return ForwardVerification(
            seed=seed,
            horizon=horizon,
            future_samples=len(future),
            end_date=None,
            support_return_floor_pct=None,
            end_return_pct=None,
            max_rebound_pct=None,
            future_main_flow=None,
            support_held=None,
            price_recovered=None,
            flow_reversed=None,
            verdict="inconclusive",
            evidence=("not_enough_future_samples",),
        )

    closes = [item.quote.price for item in future if item.quote is not None]
    future_flow = sum(item.fund_flow.main_net_inflow for item in future)
    end_date = future[-1].timestamp.date().isoformat()
    if not closes:
        return ForwardVerification(
            seed=seed,
            horizon=horizon,
            future_samples=len(future),
            end_date=end_date,
            support_return_floor_pct=None,
            end_return_pct=None,
            max_rebound_pct=None,
            future_main_flow=future_flow,
            support_held=None,
            price_recovered=None,
            flow_reversed=future_flow > 0,
            verdict="inconclusive",
            evidence=("future_price_missing",),
        )

    returns = [(close / seed.close - 1) * 100 for close in closes]
    support_floor = min(returns)
    end_return = returns[-1]
    rebound = max(returns)
    support_held = support_floor >= -5.0
    price_recovered = end_return > 0 or rebound >= 3.0
    flow_reversed = future_flow > 0
    passed = sum((support_held, price_recovered, flow_reversed))
    if passed >= 2:
        verdict = "confirmed"
    elif support_floor <= -5.0 and not flow_reversed:
        verdict = "failed"
    else:
        verdict = "inconclusive"
    evidence = (
        f"support_held={support_held}",
        f"price_recovered={price_recovered}",
        f"flow_reversed={flow_reversed}",
        f"passed={passed}/3",
    )
    return ForwardVerification(
        seed=seed,
        horizon=horizon,
        future_samples=len(future),
        end_date=end_date,
        support_return_floor_pct=support_floor,
        end_return_pct=end_return,
        max_rebound_pct=rebound,
        future_main_flow=future_flow,
        support_held=support_held,
        price_recovered=price_recovered,
        flow_reversed=flow_reversed,
        verdict=verdict,
        evidence=evidence,
    )


def _seed_from_signal(signal: StockSignal | None) -> AccumulationSeed:
    if signal is None:
        raise ValueError("signal must not be None")
    quote = signal.quote
    flow = signal.fund_flow
    tags = tuple(tag.value for tag in signal.pattern_tags)
    failed_breakout = PatternTag.FAILED_BREAKOUT in signal.pattern_tags
    weak_price = bool(
        (flow.change_pct is not None and flow.change_pct < 0)
        or (quote is not None and quote.change_pct is not None and quote.change_pct < 0)
    )
    apparent_selling = (
        flow.main_net_inflow < 0
        and flow.super_large_net_inflow < 0
        and flow.large_net_inflow < 0
    )
    small_order_absorption = flow.small_net_inflow > 0
    return AccumulationSeed(
        trade_date=signal.timestamp.date().isoformat(),
        symbol=signal.symbol,
        close=quote.price if quote else None,
        main_flow=flow.main_net_inflow,
        main_pct=flow.main_net_inflow_pct,
        super_large_flow=flow.super_large_net_inflow,
        large_flow=flow.large_net_inflow,
        small_flow=flow.small_net_inflow,
        change_pct=flow.change_pct if flow.change_pct is not None else (quote.change_pct if quote else None),
        pattern_tags=tags,
        apparent_selling=apparent_selling,
        small_order_absorption=small_order_absorption,
        weak_price=weak_price,
        failed_breakout=failed_breakout,
    )


def _current_status(seed: AccumulationSeed | None) -> tuple[str, tuple[str, ...]]:
    if seed is None:
        return "no_current_signal", ("fetch a current quote and fund-flow row first",)
    if not seed.is_candidate:
        return "not_candidate", ("current footprint does not match hidden-accumulation candidate rules",)
    return (
        "pending_future_confirmation",
        (
            "candidate footprint is present, but hidden accumulation is not proven today",
            "wait for future support, price recovery, and main-flow reversal evidence",
        ),
    )


def _point_in_time_status(
    *,
    seed: AccumulationSeed,
    resolved: int,
    confirmation_rate: float | None,
    min_cases: int,
    min_confirmation_rate_pct: float,
) -> tuple[str, tuple[str, ...]]:
    if not seed.is_candidate:
        return "not_candidate", ("current signal is not a disguised-accumulation candidate",)
    if resolved < min_cases:
        return (
            "history_insufficient_wait",
            (
                f"resolved_cases={resolved} below min_cases={min_cases}",
                "candidate requires more point-in-time historical evidence before probing",
            ),
        )
    if confirmation_rate is not None and confirmation_rate >= min_confirmation_rate_pct:
        return (
            "history_supported_probe_allowed",
            (
                f"resolved_cases={resolved}",
                f"confirmation_rate={confirmation_rate:.2f}%",
                "small probe is allowed, but full entry still requires future confirmation",
            ),
        )
    return (
        "history_weak_wait",
        (
            f"resolved_cases={resolved}",
            f"confirmation_rate={confirmation_rate:.2f}%" if confirmation_rate is not None else "confirmation_rate=-",
            "wait for support/recovery/flow confirmation before entry",
        ),
    )


def _conclusion(
    *,
    resolved: int,
    confirmed: int,
    failed: int,
    confirmation_rate: float | None,
    min_cases: int,
    current_seed: AccumulationSeed | None,
) -> str:
    if current_seed is not None and current_seed.is_candidate and resolved < min_cases:
        return "current_candidate_but_history_insufficient"
    if resolved < min_cases:
        return "not_enough_historical_cases"
    if confirmation_rate is not None and confirmation_rate >= 60:
        return "historically_supported_but_current_still_pending"
    if failed > confirmed:
        return "historically_more_often_failed"
    return "historically_inconclusive"


def _money(value: float | None) -> str:
    if value is None:
        return "-"
    abs_value = abs(value)
    if abs_value >= 100000000:
        return f"{value / 100000000:.2f}e8"
    if abs_value >= 10000:
        return f"{value / 10000:.2f}w"
    return f"{value:.2f}"


def _pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}%"


def _fmt(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}"
