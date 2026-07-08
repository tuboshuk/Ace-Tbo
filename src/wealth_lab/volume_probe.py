"""Point-in-time validation for volume-price trial entries."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from math import log, sqrt
from statistics import fmean
from collections.abc import Iterator

from wealth_lab.models import Bar
from wealth_lab.volume_replay import VolumePriceNode, build_volume_price_node


DEFAULT_ALLOWED_VOLUME_PROBE_NODES = (
    "volume_breakout",
    "shrink_pullback",
    "dry_up_base",
    "quiet_consolidation",
)


@dataclass(frozen=True)
class VolumeProbeConfig:
    """Validation thresholds for a volume-price trial entry."""

    window: int = 20
    exit_offset_bars: int = 2
    min_cases: int = 5
    min_win_rate_pct: float = 55.0
    min_avg_return_pct: float = 0.20
    allowed_node_types: tuple[str, ...] = DEFAULT_ALLOWED_VOLUME_PROBE_NODES


@dataclass(frozen=True)
class OpeningExpectationConfig:
    """Settings for point-in-time next-open expectation."""

    window: int = 20
    recent_days: int = 5
    min_cases: int = 5
    max_cases: int = 12
    band_multiplier: float = 1.25
    min_band_width_pct: float = 1.50


@dataclass(frozen=True)
class VolumeProbeOutcome:
    """One resolved historical same-node outcome."""

    signal_date: date
    node_type: str
    entry_date: date
    exit_date: date
    entry_price: float
    exit_price: float
    return_pct: float


@dataclass(frozen=True)
class OpeningExpectationCase:
    """One prior same-node next-open sample."""

    signal_date: date
    node_type: str
    gap_pct: float
    distance: float
    amount_ratio: float | None
    recent_volume_ratio: float | None
    node_volume_ratio: float | None
    change_pct: float | None


@dataclass(frozen=True)
class OpeningExpectation:
    """Expected next-open gap derived from prior same-node samples."""

    signal_date: date
    node_type: str
    expected_gap_pct: float | None
    low_gap_pct: float | None
    high_gap_pct: float | None
    actual_gap_pct: float
    sample_cases: int
    classification: str
    reason: str
    cases: tuple[OpeningExpectationCase, ...] = ()


@dataclass(frozen=True)
class VolumeProbeContext:
    """Point-in-time same-node evidence for the current bar."""

    as_of_date: date
    node: VolumePriceNode
    resolved_cases: int
    win_rate_pct: float | None
    avg_return_pct: float | None
    avg_win_pct: float | None
    avg_loss_pct: float | None
    passed: bool
    reason: str
    outcomes: tuple[VolumeProbeOutcome, ...] = ()


def build_point_in_time_volume_probe_context(
    bars: list[Bar],
    index: int,
    config: VolumeProbeConfig | None = None,
) -> VolumeProbeContext:
    """Validate today's volume-price node using only prior resolved outcomes.

    A resolved outcome uses the bar after the signal as entry and the configured
    later bar as exit. With the default ``exit_offset_bars=2``, this simulates:
    signal day close -> next trading day open buy -> following trading day open
    sell, which avoids same-day sell assumptions in A-share replay.
    """

    if not bars:
        raise ValueError("bars must not be empty")
    if index < 0 or index >= len(bars):
        raise IndexError("index out of range")
    probe_config = config or VolumeProbeConfig()
    _validate_config(probe_config)

    current = bars[index]
    current_node = build_volume_price_node(
        bar=current,
        previous_bars=bars[max(0, index - probe_config.window):index],
        signal=None,
    )
    outcomes = tuple(
        _iter_resolved_outcomes(
            bars=bars,
            index=index,
            current_node=current_node,
            config=probe_config,
        )
    )
    stats = _stats(outcomes)
    passed, reason = _gate(
        node=current_node,
        resolved_cases=len(outcomes),
        win_rate_pct=stats["win_rate_pct"],
        avg_return_pct=stats["avg_return_pct"],
        config=probe_config,
    )
    return VolumeProbeContext(
        as_of_date=current.trade_date,
        node=current_node,
        resolved_cases=len(outcomes),
        win_rate_pct=stats["win_rate_pct"],
        avg_return_pct=stats["avg_return_pct"],
        avg_win_pct=stats["avg_win_pct"],
        avg_loss_pct=stats["avg_loss_pct"],
        passed=passed,
        reason=reason,
        outcomes=outcomes,
    )


def build_volume_probe_opening_expectation(
    bars: list[Bar],
    signal_index: int,
    execution_index: int,
    config: OpeningExpectationConfig | None = None,
) -> OpeningExpectation:
    """Estimate whether the actual next open is normal for this volume state.

    The expectation uses only signal-day data and prior same-node next-open
    samples whose opening price is already known before the current signal day.
    Similarity is ranked by recent成交额 ratio, recent volume ratio, node volume
    ratio, price change, and range position.
    """

    if not bars:
        raise ValueError("bars must not be empty")
    if signal_index < 0 or signal_index >= len(bars):
        raise IndexError("signal_index out of range")
    if execution_index <= signal_index or execution_index >= len(bars):
        raise IndexError("execution_index must point to a later bar")
    expectation_config = config or OpeningExpectationConfig()
    _validate_opening_config(expectation_config)

    signal_bar = bars[signal_index]
    execution_bar = bars[execution_index]
    if signal_bar.close <= 0:
        raise ValueError("signal close must be positive")
    actual_gap_pct = (execution_bar.open / signal_bar.close - 1) * 100
    current_node = build_volume_price_node(
        bar=signal_bar,
        previous_bars=bars[max(0, signal_index - expectation_config.window):signal_index],
        signal=None,
    )
    current_features = _opening_features(
        bars=bars,
        index=signal_index,
        node=current_node,
        config=expectation_config,
    )
    cases = tuple(
        sorted(
            _iter_opening_cases(
                bars=bars,
                signal_index=signal_index,
                current_node=current_node,
                current_features=current_features,
                config=expectation_config,
            ),
            key=lambda item: item.distance,
        )[:expectation_config.max_cases]
    )
    if len(cases) < expectation_config.min_cases:
        return OpeningExpectation(
            signal_date=signal_bar.trade_date,
            node_type=current_node.node_type,
            expected_gap_pct=None,
            low_gap_pct=None,
            high_gap_pct=None,
            actual_gap_pct=actual_gap_pct,
            sample_cases=len(cases),
            classification="insufficient_opening_history",
            reason=(
                "insufficient_same_node_opening_cases:"
                f"{len(cases)}/{expectation_config.min_cases}"
            ),
            cases=cases,
        )

    weights = [1 / (1 + item.distance) for item in cases]
    weight_sum = sum(weights)
    expected_gap_pct = sum(
        item.gap_pct * weight for item, weight in zip(cases, weights)
    ) / weight_sum
    variance = sum(
        weight * (item.gap_pct - expected_gap_pct) ** 2
        for item, weight in zip(cases, weights)
    ) / weight_sum
    band_width = max(
        sqrt(variance) * expectation_config.band_multiplier,
        expectation_config.min_band_width_pct,
    )
    low_gap_pct = expected_gap_pct - band_width
    high_gap_pct = expected_gap_pct + band_width
    return OpeningExpectation(
        signal_date=signal_bar.trade_date,
        node_type=current_node.node_type,
        expected_gap_pct=expected_gap_pct,
        low_gap_pct=low_gap_pct,
        high_gap_pct=high_gap_pct,
        actual_gap_pct=actual_gap_pct,
        sample_cases=len(cases),
        classification=_classify_opening_gap(
            actual_gap_pct=actual_gap_pct,
            low_gap_pct=low_gap_pct,
            high_gap_pct=high_gap_pct,
        ),
        reason=(
            "nearest_same_node_opening_distribution "
            f"amount_ratio={_fmt(current_features.amount_ratio)} "
            f"recent_volume_ratio={_fmt(current_features.recent_volume_ratio)} "
            f"node_volume_ratio={_fmt(current_features.node_volume_ratio)} "
            f"change={_fmt(current_features.change_pct)}"
        ),
        cases=cases,
    )


def _iter_resolved_outcomes(
    *,
    bars: list[Bar],
    index: int,
    current_node: VolumePriceNode,
    config: VolumeProbeConfig,
) -> Iterator[VolumeProbeOutcome]:
    latest_case_index = index - config.exit_offset_bars
    if latest_case_index < 1:
        return
    for case_index in range(1, latest_case_index + 1):
        node = build_volume_price_node(
            bar=bars[case_index],
            previous_bars=bars[max(0, case_index - config.window):case_index],
            signal=None,
        )
        if node.node_type != current_node.node_type:
            continue
        entry_bar = bars[case_index + 1]
        exit_bar = bars[case_index + config.exit_offset_bars]
        if entry_bar.open <= 0:
            continue
        return_pct = (exit_bar.open / entry_bar.open - 1) * 100
        yield VolumeProbeOutcome(
            signal_date=bars[case_index].trade_date,
            node_type=node.node_type,
            entry_date=entry_bar.trade_date,
            exit_date=exit_bar.trade_date,
            entry_price=entry_bar.open,
            exit_price=exit_bar.open,
            return_pct=return_pct,
        )


@dataclass(frozen=True)
class _OpeningFeatures:
    """Comparable signal-day features for opening expectation."""

    amount_ratio: float | None
    recent_volume_ratio: float | None
    node_volume_ratio: float | None
    range_position_pct: float | None
    change_pct: float | None


def _iter_opening_cases(
    *,
    bars: list[Bar],
    signal_index: int,
    current_node: VolumePriceNode,
    current_features: _OpeningFeatures,
    config: OpeningExpectationConfig,
) -> Iterator[OpeningExpectationCase]:
    if signal_index < 1:
        return
    latest_case_index = signal_index - 1
    for case_index in range(1, latest_case_index + 1):
        case_bar = bars[case_index]
        entry_bar = bars[case_index + 1]
        if case_bar.close <= 0 or entry_bar.open <= 0:
            continue
        case_node = build_volume_price_node(
            bar=case_bar,
            previous_bars=bars[max(0, case_index - config.window):case_index],
            signal=None,
        )
        if case_node.node_type != current_node.node_type:
            continue
        case_features = _opening_features(
            bars=bars,
            index=case_index,
            node=case_node,
            config=config,
        )
        yield OpeningExpectationCase(
            signal_date=case_bar.trade_date,
            node_type=case_node.node_type,
            gap_pct=(entry_bar.open / case_bar.close - 1) * 100,
            distance=_feature_distance(current_features, case_features),
            amount_ratio=case_features.amount_ratio,
            recent_volume_ratio=case_features.recent_volume_ratio,
            node_volume_ratio=case_features.node_volume_ratio,
            change_pct=case_features.change_pct,
        )


def _opening_features(
    *,
    bars: list[Bar],
    index: int,
    node: VolumePriceNode,
    config: OpeningExpectationConfig,
) -> _OpeningFeatures:
    bar = bars[index]
    previous_bars = bars[max(0, index - config.recent_days):index]
    return _OpeningFeatures(
        amount_ratio=_ratio(_amount_proxy(bar), [_amount_proxy(item) for item in previous_bars]),
        recent_volume_ratio=_ratio(float(bar.volume), [float(item.volume) for item in previous_bars]),
        node_volume_ratio=node.volume_ratio,
        range_position_pct=node.range_position_pct,
        change_pct=bar.change_pct,
    )


def _feature_distance(current: _OpeningFeatures, case: _OpeningFeatures) -> float:
    distance = 0.0
    distance += 0.35 * _log_ratio_distance(current.amount_ratio, case.amount_ratio)
    distance += 0.25 * _log_ratio_distance(
        current.recent_volume_ratio,
        case.recent_volume_ratio,
    )
    distance += 0.20 * _log_ratio_distance(
        current.node_volume_ratio,
        case.node_volume_ratio,
    )
    distance += 0.12 * _scaled_abs_distance(current.change_pct, case.change_pct, 5.0)
    distance += 0.08 * _scaled_abs_distance(
        current.range_position_pct,
        case.range_position_pct,
        100.0,
    )
    return distance


def _amount_proxy(bar: Bar) -> float:
    if bar.amount is not None and bar.amount > 0:
        return bar.amount
    return bar.close * bar.volume


def _ratio(value: float, history: list[float]) -> float | None:
    if value <= 0 or not history:
        return None
    positives = [item for item in history if item > 0]
    if not positives:
        return None
    average = fmean(positives)
    if average <= 0:
        return None
    return value / average


def _log_ratio_distance(left: float | None, right: float | None) -> float:
    if left is None or right is None or left <= 0 or right <= 0:
        return 0.50
    return abs(log(left / right))


def _scaled_abs_distance(
    left: float | None,
    right: float | None,
    scale: float,
) -> float:
    if left is None or right is None or scale <= 0:
        return 0.50
    return abs(left - right) / scale


def _classify_opening_gap(
    *,
    actual_gap_pct: float,
    low_gap_pct: float,
    high_gap_pct: float,
) -> str:
    if actual_gap_pct > high_gap_pct:
        return "overheated_high_open"
    if actual_gap_pct < low_gap_pct:
        return "below_expected_open"
    return "expected_open"


def _stats(outcomes: tuple[VolumeProbeOutcome, ...]) -> dict[str, float | None]:
    if not outcomes:
        return {
            "win_rate_pct": None,
            "avg_return_pct": None,
            "avg_win_pct": None,
            "avg_loss_pct": None,
        }

    returns = [item.return_pct for item in outcomes]
    wins = [item for item in returns if item > 0]
    losses = [item for item in returns if item < 0]
    return {
        "win_rate_pct": len(wins) / len(outcomes) * 100,
        "avg_return_pct": fmean(returns),
        "avg_win_pct": fmean(wins) if wins else None,
        "avg_loss_pct": fmean(losses) if losses else None,
    }


def _gate(
    *,
    node: VolumePriceNode,
    resolved_cases: int,
    win_rate_pct: float | None,
    avg_return_pct: float | None,
    config: VolumeProbeConfig,
) -> tuple[bool, str]:
    if node.node_type == "insufficient_history":
        return False, "insufficient_history_for_current_node"
    if node.node_type not in config.allowed_node_types:
        return False, f"node_not_allowed:{node.node_type}"
    if resolved_cases < config.min_cases:
        return False, f"insufficient_cases:{resolved_cases}/{config.min_cases}"
    if win_rate_pct is None or win_rate_pct < config.min_win_rate_pct:
        return False, (
            f"win_rate_below_min:{_fmt(win_rate_pct)}<"
            f"{config.min_win_rate_pct:.2f}"
        )
    if avg_return_pct is None or avg_return_pct < config.min_avg_return_pct:
        return False, (
            f"avg_return_below_min:{_fmt(avg_return_pct)}<"
            f"{config.min_avg_return_pct:.2f}"
        )
    return True, "passed_same_node_history_gate"


def _validate_config(config: VolumeProbeConfig) -> None:
    if config.window <= 0:
        raise ValueError("window must be positive")
    if config.exit_offset_bars < 2:
        raise ValueError("exit_offset_bars must be at least 2")
    if config.min_cases < 0:
        raise ValueError("min_cases must not be negative")
    if not config.allowed_node_types:
        raise ValueError("allowed_node_types must not be empty")


def _validate_opening_config(config: OpeningExpectationConfig) -> None:
    if config.window <= 0:
        raise ValueError("window must be positive")
    if config.recent_days <= 0:
        raise ValueError("recent_days must be positive")
    if config.min_cases < 0:
        raise ValueError("min_cases must not be negative")
    if config.max_cases <= 0:
        raise ValueError("max_cases must be positive")
    if config.max_cases < config.min_cases:
        raise ValueError("max_cases must be greater than or equal to min_cases")
    if config.band_multiplier <= 0:
        raise ValueError("band_multiplier must be positive")
    if config.min_band_width_pct < 0:
        raise ValueError("min_band_width_pct must not be negative")


def _fmt(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}"
