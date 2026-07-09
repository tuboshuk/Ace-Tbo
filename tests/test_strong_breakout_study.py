import json
from pathlib import Path

from wealth_lab.strong_breakout_study import (
    build_strong_breakout_study,
    render_strong_breakout_study,
)


def test_strong_breakout_study_filters_exact_structure(tmp_path: Path) -> None:
    jsonl_path = tmp_path / "training.jsonl"
    records = [
        {"kind": "training_run", "run_id": "run-1"},
        {
            "kind": "candidate_result",
            "candidate": "volume_price_breakout_opening_guard_probe",
            "symbol": "000592",
            "trade_stories": [
                _story(
                    symbol="000592",
                    entry="2025-10-31",
                    return_pct=29.92,
                    stage="volume_node:volume_breakout",
                ),
                _story(
                    symbol="000592",
                    entry="2025-11-06",
                    return_pct=-11.35,
                    stage="accumulation_watch",
                ),
            ],
        },
        {
            "kind": "candidate_result",
            "candidate": "other",
            "symbol": "600879",
            "trade_stories": [
                _story(
                    symbol="600879",
                    entry="2025-12-15",
                    return_pct=25.89,
                    stage="volume_node:volume_breakout",
                )
            ],
        },
    ]
    jsonl_path.write_text(
        "\n".join(json.dumps(item, ensure_ascii=False) for item in records),
        encoding="utf-8",
    )

    study = build_strong_breakout_study(jsonl_path=jsonl_path)

    assert study.run_id == "run-1"
    assert study.candidate_results == 1
    assert study.trade_count == 1
    assert study.win_rate_pct == 100
    assert study.avg_return_pct == 29.92

    report = render_strong_breakout_study(study)

    assert "Strong Breakout Replication Study" in report
    assert "volume_node:volume_breakout" in report
    assert "000592" in report
    assert "600879" not in report


def _story(
    *,
    symbol: str,
    entry: str,
    return_pct: float,
    stage: str,
) -> dict[str, object]:
    return {
        "symbol": symbol,
        "entry_date": entry,
        "exit_date": "2025-11-07",
        "return_pct": return_pct,
        "actual_holding_days": 5,
        "confirmations": 4,
        "warnings": 1,
        "invalidations": 0,
        "exit_reason": "max_hold",
        "verdict": "thesis_confirmed",
        "holding_evidence": "confirming",
        "thesis": {
            "buy_type": "breakout_start",
            "vpa_archetype": "effort_vs_result_breakout",
            "stage": stage,
        },
    }
