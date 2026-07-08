# Agent Supervision Status

This file tracks the concurrent worker run for the 10% annual-return research target.

Boundary: paper replay and research only. A candidate is not treated as successful unless it passes the project promotion gate and the replay assessment says it is on track for the target with enough samples.

## Target Gate

- target_annual_return: 10%
- must use repeatable historical replay, not a single cherry-picked trade
- must keep sample evidence explicit: symbols, closed trades, expectancy, drawdown, skipped orders
- must log every program action in `docs/persistent-training-log.md`
- must not promote a candidate that only improves one stock while degrading the 6-symbol pool

## Workers

worker | agent_id | responsibility | write scope | status
--- | --- | --- | --- | ---
A knowledge | `019f3bc3-a3b6-7290-944a-b0d60a31bff1` | Build a program-usable investment knowledge base | `docs/investment-knowledge-base.md` | completed; knowledge base reviewed
B strategy | `019f3bc3-cbcc-7411-acb8-f12a87c1340e` | Make one conservative strategy improvement or candidate | strategy/training code and tests | completed second iteration; added `volume_price_intent_filtered_probe` and `volume_price_risk_sized_probe`, best candidate still below 10% target
C recorder | `019f3bc3-d9b1-7e63-aa6b-5683cc4ce7d6` | Build a version trade-behavior journal mechanism | `docs/version-trade-behavior-log.md`, `src/wealth_lab/version_journal.py`, `tests/test_version_journal.py` | completed; `python -m pytest tests\test_version_journal.py` passed
D failure analysis | `019f3be9-72d3-7221-a2d6-4a80a5911f48` | Read-only analysis of v017 failed samples | training artifacts only | completed; identified that risk sizing amplified low-edge dry-up nodes and informed `volume_price_support_quality_probe`
E expansion analysis | `019f3c01-b01c-75d1-9794-5ffd4465c072` | Read-only analysis for expanding high-quality v018 trades | training artifacts only | completed; informed v020 quiet exception direction
F strategy | `019f3c01-f6ea-7712-bd79-1b764e721ae8` | Implement independent node-quality expansion candidate | strategy/training code and tests | completed; added `volume_price_node_quality_expansion_probe`, but replay underperformed v018
G v020 recorder | `019f3c14-e9f8-7c03-809b-51a57ae9903f` | Record v020 supervision and behavior evidence | docs only | completed; recorded v020 as OBSERVE, not promoted
H v020 evidence | `019f3c14-c1e8-7d90-ba4b-1811170bf92a` | Read-only analysis of v020 added quiet trades | training artifacts and code only | completed; identified `cases` and `distribution_score` as useful differentiators
I v021 strategy | `019f3c1c-40d0-7ac1-a3cf-93f7243fc8f4` | Implement quiet exception flow/sample/distribution guard candidate | strategy/training code and tests | completed; added `volume_price_quiet_exception_flow_guard_probe`
J v023 evidence | `019f3c3c-66c1-7091-baa9-18cdcc81df0e` | Read-only analysis of `002031` low-expectancy trades | training artifacts and code only | completed; identified `dry_up_base` in markdown/weekly-down risk as the main low-expectancy source

## Supervisor Notes

- Do not treat 10% annual return as achieved until training output proves it.
- If workers conflict, prefer the change with broader-symbol validation and clearer no-future-leakage behavior.
- If the strategy worker improves only one symbol, keep it as an experimental candidate instead of promoting it.
- If the recorder worker adds tooling, verify it does not alter replay results.
- Prior best comparison candidate: `volume_price_support_quality_probe` improved aggregate return to `0.14%` with lower average drawdown `0.08%`, but closed trades fell to `11`; still OBSERVE, not a 10% annual-return solution.
- Prior rejected/observation candidate: `volume_price_node_quality_expansion_probe` reduced trades to `2` and aggregate return to `0.07%`; do not promote because it over-filtered non-dry-up nodes and failed the expansion goal.

## v020 Supervision Update

- Latest training command: `python run.py train-replay 000620 000001 300750 600519 002594 300059 --days 370 --initial-cash 100000`.
- Latest training artifacts: `runtime/training/20260707T101210Z-summary.md` and `runtime/training/20260707T101210Z-training.jsonl`.
- Full test result: `python -m pytest` => `70 passed`.
- Latest observation candidate: `volume_price_quiet_exception_probe`; 6 symbols, closed trades `14`, low-confidence samples `1`, no-trade samples `2`, average return `0.13%`, average max drawdown `0.11%`, average score `30.3`.
- Comparison: v020 raised closed trades versus v018 (`14` vs `11`) and v019 (`14` vs `2`), and raised average score versus v018 (`30.3` vs `25.5`) and v019 (`30.3` vs `6.7`), but average return is below v018 (`0.13%` vs `0.14%`) and drawdown is worse than v018 (`0.11%` vs `0.08%`).
- Promotion decision: `OBSERVE`; do not promote, do not count as 10%, and do not make it the default strategy because it worsened `000001` and increased drawdown even though trade count and score improved.

## v021 Supervision Update

- Latest training command: `python run.py train-replay 000620 000001 300750 600519 002594 300059 --days 370 --initial-cash 100000`.
- Latest training artifacts: `runtime/training/20260707T103054Z-summary.md` and `runtime/training/20260707T103054Z-training.jsonl`.
- Full test result: `python -m pytest` => `72 passed`.
- New observation candidate: `volume_price_quiet_exception_flow_guard_probe`; 6 symbols, closed trades `12`, low-confidence samples `1`, no-trade samples `2`, average return `0.15%`, average max drawdown `0.08%`, average score `29.7`.
- Comparison: v021 improved average return versus v018 (`0.15%` vs `0.14%`) and v020 (`0.15%` vs `0.13%`), restored drawdown to v018 level (`0.08%`), and reduced `000001` from v020's `3` closed trades / `-0.21%` back to `1` closed trade / `-0.09%`; it kept `002594` at `5` closed trades / `0.41%`.
- Promotion decision: `OBSERVE`; do not promote or count as 10% because aggregate return is still far below target and the evidence score remains below the promotion threshold.

## v022 Two-Symbol Diagnostic Update

- User narrowed the current scope to `000620` and `002031`; paused broader-stock exploration until requested.
- Latest two-symbol command: `python run.py train-replay 000620 002031 --days 370 --initial-cash 100000`.
- Latest two-symbol artifacts: `runtime/training/20260707T104424Z-summary.md` and `runtime/training/20260707T104424Z-training.jsonl`.
- Best two-symbol aggregate candidate by this run: `volume_price_risk_sized_probe`; closed trades `27`, average return `0.27%`, average max drawdown `0.64%`, average score `52.5`.
- Current `000620` state: `WAIT_SELL_RISK`, `distribution_or_failed_breakout`, `sustained_outflow`; current buy state blocked and entry should not be treated as a fresh accumulation buy.
- Current `002031` state: `WATCH_ACCUMULATION`, `accumulation`, `sustained_inflow`; buy is still blocked because the current signal lacks a qualified trigger and the entry risk is above the configured budget.
- Supervisor decision: diagnostic only; no code change and no default-strategy promotion. The two-stock `PROMOTE_CANDIDATE` flag is weaker than the 10% goal and is not sufficient evidence.
- Next supervised work, if continued: assign analysis to split `002031` dry-up/quiet/shrink trades by flow, stage, opening gap, support distance, and follow-through; separately inspect `000620` breakout follow-through and failed-breakout sell-risk handling.

## v023 Supervision Update

- Cleanup completed: deleted `.pytest_cache` and `__pycache__` directories only. Training artifacts, proof files, docs, and SQLite evidence were preserved.
- New candidates: `volume_price_markdown_guard_probe` and `volume_price_dry_up_flow_support_guard_probe`.
- Full test result: `python -m pytest` => `77 passed`.
- Two-symbol artifacts: `runtime/training/20260707T111231Z-summary.md` and `runtime/training/20260707T111231Z-training.jsonl`.
- Six-symbol artifacts: `runtime/training/20260707T111405Z-summary.md` and `runtime/training/20260707T111405Z-training.jsonl`.
- Two-symbol result for `volume_price_dry_up_flow_support_guard_probe`: closed trades `11`, average return `1.19%`, average max drawdown `0.33%`, average score `52.5`; `002031` improved to `7` trades / `2.00%` return / `2.50%` expectancy.
- Six-symbol result for `volume_price_dry_up_flow_support_guard_probe`: closed trades `18`, average return `0.08%`, average max drawdown `0.14%`, average score `20.0`.
- Promotion decision: `OBSERVE`; it improves `002031` but does not beat v021 on the six-symbol pool and remains far below the 10% target.

## v024 Supervision Update

- Worker K monitor split: `019f3c56-c448-7e20-b7c4-e3944690f11a`; completed. Wrote `src/wealth_lab/dashboard.py` and `tests/test_dashboard.py`.
- Worker L training discipline: `019f3c57-141e-7093-997d-e112991203f4`; completed after supervisor integration. Wrote `src/wealth_lab/training.py` and `tests/test_training.py`.
- Full test result after integration: `python -m pytest` => `82 passed`.
- Cleanup completed: deleted `.pytest_cache` and `__pycache__` directories only. Training artifacts, proof files, docs, and SQLite evidence were preserved.
- Monitor behavior changed: top-level output now separates `风险异动榜` from `可交易候选榜`; high-risk distribution and failed-breakout signals cannot appear in the tradable-candidate list.
- Promotion gate changed: candidates need at least `30` closed trades, at least `2` traded symbols, positive aggregate return, and average closed-trade expectancy above `0.50%` before `PROMOTE_CANDIDATE`.
- Two-symbol artifacts: `runtime/training/20260707T113644Z-summary.md` and `runtime/training/20260707T113644Z-training.jsonl`.
- Two-symbol gate result: `volume_price_risk_sized_probe` had `27` closed trades / `0.27%` average return, and `volume_price_dry_up_flow_support_guard_probe` had `11` closed trades / `1.19%` average return; both are now `OBSERVE` due to insufficient closed trades.
- Six-symbol artifacts: `runtime/training/20260707T113753Z-summary.md` and `runtime/training/20260707T113753Z-training.jsonl`.
- Six-symbol result: best core observation candidate remains `volume_price_quiet_exception_flow_guard_probe`; `12` closed trades, `0.15%` average return, `0.08%` average max drawdown, `0.68%` average expectancy, promotion decision `OBSERVE`.
- Negative evidence: `disguised_accumulation_probe` had `48` closed trades but `-1.03%` average expectancy and `-0.51%` average return, so it remains non-promotable despite trade count.
- Supervisor decision: no candidate reached the 10% annual-return target. v024 is validation hardening, not a profit-strategy improvement.

## v025 Supervision Update

- Scope change: user identified the missing layer as trade thesis and holding-process validation, not another buy/sell parameter.
- Implementation completed in `src/wealth_lab/diagnostics.py`, `src/wealth_lab/report.py`, `src/wealth_lab/training.py`, `tests/test_diagnostics.py`, and `tests/test_training.py`.
- New evidence objects: `TradeThesis`, `ThesisCheck`, and `TradeStory`.
- Behavior changed: replay reports now describe each closed trade as an entry thesis plus daily confirmation, warning, invalidation, exit reason, return, and verdict.
- Trading behavior unchanged: v025 does not add a new strategy candidate, does not alter the buy trigger, and does not alter the sell trigger.
- Targeted test result: `python -m pytest tests\test_diagnostics.py tests\test_training.py -q` => `10 passed`.
- Full test result: `python -m pytest` => `83 passed`.
- Two-symbol artifacts: `runtime/training/20260708T011421Z-summary.md` and `runtime/training/20260708T011421Z-training.jsonl`.
- Two-symbol result: `volume_price_risk_sized_probe` had `31` closed trades / `0.50%` average return / `0.24%` average expectancy and remained `OBSERVE`; `volume_price_dry_up_flow_support_guard_probe` had `12` closed trades / `0.51%` average return / `0.71%` average expectancy and remained `OBSERVE`.
- Six-symbol artifacts: `runtime/training/20260708T011505Z-summary.md` and `runtime/training/20260708T011505Z-training.jsonl`.
- Six-symbol result: best core observation candidate `volume_price_quiet_exception_flow_guard_probe` had `11` closed trades / `0.16%` average return / `0.07%` average max drawdown / `0.81%` average expectancy and remained `OBSERVE`.
- Negative evidence: six-symbol `disguised_accumulation_probe` had `48` closed trades but `-1.03%` average expectancy and `-0.51%` average return.
- Trade story verdict counts in the six-symbol report: `thesis_confirmed=25`, `thesis_failed=113`, `warnings_confirmed_exit=38`.
- Supervisor decision: no candidate reached the 10% annual-return target. v025 is a process-understanding and evidence upgrade; the next supervised step should analyze failed thesis clusters before changing hold/add/exit behavior.

## v026 Supervision Update

- User requested continued multi-subagent mode with A analysis, B solution design, C implementation/validation, and supervisor control to prevent unstable parameter churn.
- Worker A analysis: `019f3f51-ee83-7bc3-ac50-8f332e9f3ced`; completed read-only. Main finding: target failure is not one missing indicator, but failure to satisfy sample count, cross-symbol breadth, positive return, and positive expectancy at the same time. Priority failure clusters were proof-probe entries, dry-up absorption tests, shrink pullback support failures, and weak accumulation confirmations.
- Worker B solution: `019f3f52-3fe0-7f91-bfd8-56dc3f4b9416`; completed read-only. Proposed a research-only `PositionActionReview` layer mapping opening gap buckets, opening classification, support distance, and thesis verdict into observe/probe/buy/reduce/exit labels.
- Worker C implementation: `019f3f58-7d53-7700-b2c6-0e40dce185dc`; completed. Wrote `src/wealth_lab/diagnostics.py`, `src/wealth_lab/report.py`, `src/wealth_lab/training.py`, `tests/test_diagnostics.py`, and `tests/test_training.py`.
- Supervisor correction: support distance in diagnostics was aligned with the existing execution formula: `(entry_open - support) / entry_open`.
- Trading behavior changed: no. `PositionActionReview` is diagnostics only and does not drive `PaperBroker`, order sizing, sell execution, or live decisions.
- Targeted test result after supervisor correction: `python -m pytest tests\test_diagnostics.py tests\test_training.py -q` => `13 passed`.
- Full test result: `python -m pytest` => `86 passed`.
- New stock pool: `000620`, `002031`, `601929`, `000592`, `600879`, `002255`, `002279`, `000725`, `600478`, `002369`.
- Final training artifacts: `runtime/training/20260708T014023Z-summary.md` and `runtime/training/20260708T014023Z-training.jsonl`.
- Expanded-pool result: `volume_price_support_quality_probe` and `volume_price_quiet_exception_flow_guard_probe` each had `38` closed trades across `9` traded symbols, `0.31%` average expectancy, `-0.07%` average return, and `0.44%` average max drawdown. Both remain `OBSERVE` because `0.31% < 0.50%` cost/slippage buffer.
- Negative evidence: `disguised_accumulation_probe` expanded to `106` closed trades but stayed negative with `-0.97%` average expectancy and `-0.82%` average return.
- Position action evidence: core candidates show `exit` groups at roughly `18` trades / `-2.36%` average return, while `buy_50` groups show `8` trades / `3.58%` average return. This is only a diagnostic split, not proof that executing the labels will work.
- Improvement gate for future C work: same pool and duration, relative improvement at least `5%`, absolute return improvement at least `0.10pp`, expectancy improvement at least `0.05pp`, no regression in closed-trade count, traded-symbol count, or drawdown. Otherwise treat the change as ineffective and send it back to A analysis.
- Supervisor decision: no candidate reached the 10% annual-return target. v026 is a supervised diagnostics upgrade and broader-pool baseline, not a promoted trading strategy.

## v027 Supervision Update

- User provided a classic reading framework: VPA/Wyckoff/Weis, Nison/Bulkowski/Edwards-Magee, O'Neil/Minervini/Shannon, plus Livermore, and asked to convert it into rules for before-entry, 1-3 day follow-through, holding, and exit.
- Worker A analysis: `019f3f69-485b-78c2-b77b-017d7d0a401f`; completed read-only. Main finding: book rules must become trade-thesis questions and validation fields; `PositionActionReview` and `TradeStory.verdict` remain observation labels only.
- Worker B solution: `019f3f69-825c-70b3-861a-4bdf4696e801`; completed read-only. Proposed a minimal diagnostic-only `KnowledgeHypothesisReview` layer; no new candidate, no execution change, no Markdown runtime parsing.
- Supervisor/C implementation completed in `src/wealth_lab/diagnostics.py`, `src/wealth_lab/report.py`, `src/wealth_lab/training.py`, `tests/test_diagnostics.py`, and `tests/test_training.py`.
- Trading behavior changed: no. `KnowledgeHypothesisReview` is diagnostics/reporting only and does not drive `TradeDiscipline`, `ReplayRunner`, `PaperBroker`, order sizing, or live decisions.
- Knowledge mapping added:
  - `coulling_wyckoff_weis` -> `volume_price` / `effort_result_must_confirm_stage`
  - `nison_bulkowski_edwards_magee` -> `pattern_structure` / `pattern_requires_location_and_confirmation`
  - `shannon_livermore` -> `opening_attention` / `opening_gap_changes_risk_reward`
  - `edwards_magee_livermore` -> `support_risk` / `support_distance_controls_probe_size`
  - `oneil_minervini_livermore` -> `invalidation` / `hold_only_while_thesis_is_valid`
- Targeted test result: `python -m pytest tests\test_diagnostics.py tests\test_training.py -q` => `14 passed`.
- Full test result: `python -m pytest` => `87 passed`.
- Final training artifacts: `runtime/training/20260708T015641Z-summary.md` and `runtime/training/20260708T015641Z-training.jsonl`.
- Expanded-pool result stayed below gate: `volume_price_support_quality_probe` and `volume_price_quiet_exception_flow_guard_probe` each had `38` closed trades across `9` traded symbols, `0.31%` average expectancy, `-0.08%` average return, and `0.46%` average max drawdown. Both remain `OBSERVE` because `0.31% < 0.50%` cost/slippage buffer.
- Negative evidence: `disguised_accumulation_probe` had `106` closed trades but stayed negative with `-0.97%` average expectancy and `-0.84%` average return.
- Knowledge diagnostics evidence: core `volume_price_quiet_exception_flow_guard_probe` marked `effort_vs_result_breakout` as `11` trades / `54.55%` win rate / `2.35%` average return / `REVIEW_CANDIDATE`, while `no_supply_pullback_or_wash` stayed `OBSERVE_ONLY` at `21` trades / `-0.52%` average return.
- Supervisor decision: no candidate reached the 10% annual-return target. v027 is a knowledge-to-diagnostics upgrade, not a promoted trading strategy. Next work should analyze why effective breakout confirmation differs from failed shrink/pullback scripts before proposing any execution-layer change.

## v028 Supervision Update

- User explicitly identified the missing work: only trade the proven observation cluster, block failed clusters, and move learning results from reports into execution discipline.
- Worker A analysis: `019f3f7d-79e8-75e2-bff6-2e3823dafcd8`; completed read-only. It confirmed the mapping `volume_breakout -> effort_vs_result_breakout`, `shrink_pullback -> no_supply_pullback_or_wash`, and `quiet_consolidation -> quiet_consolidation_no_supply_test`.
- Worker B baseline: `019f3f7d-a84d-7a00-92cb-4d703a28a9d7`; completed read-only. It fixed the v027 comparison baseline at `38` closed trades, `9` traded symbols, `0.31%` average expectancy, `-0.08%` average return, and `0.46%` average max drawdown for the core volume-price candidates.
- Supervisor/C implementation completed in `src/wealth_lab/trade_discipline.py`, `src/wealth_lab/replay.py`, `src/wealth_lab/training.py`, `tests/test_volume_probe.py`, and `tests/test_training.py`.
- Trading behavior changed: yes, but only for the new experimental candidate `volume_price_breakout_follow_through_probe`. Existing core candidates and normal strategy modes keep their existing behavior.
- Execution discipline added:
  - Only `volume_breakout` can enter the new candidate.
  - `shrink_pullback`, `quiet_consolidation`, and `dry_up_base` are blocked by the volume-probe allowed-node list for this candidate.
  - `invalidated` exits next open, no follow-through after 1-3 bars exits, and confirmed trials can hold to 3-5 bars.
- Targeted test result: `python -m pytest tests\test_volume_probe.py tests\test_training.py -q` => `45 passed`.
- Full test result: `python -m pytest` => `92 passed`.
- Final training artifacts: `runtime/training/20260708T021623Z-summary.md` and `runtime/training/20260708T021623Z-training.jsonl`.
- Same-run core result: `volume_price_support_quality_probe` and `volume_price_quiet_exception_flow_guard_probe` each had `38` closed trades across `9` traded symbols, `0.31%` average expectancy, `-0.05%` average return, and `0.43%` average max drawdown. Both remain `OBSERVE`.
- New candidate result: `volume_price_breakout_follow_through_probe` had `9` closed trades across `4` traded symbols, `5.57%` average expectancy, `0.21%` average return, and `0.20%` average max drawdown.
- Knowledge diagnostics for the new candidate: `effort_vs_result_breakout` had `9` trades, `55.56%` win rate, `5.57%` average return, and `REVIEW_CANDIDATE`.
- Supervisor decision: do not promote. The narrow breakout candidate improved return and expectancy, but it regressed closed-trade count from `38` to `9` and traded symbols from `9` to `4`; it therefore fails the no-regression part of the 5% improvement discipline and is not a 10% annual-return strategy.
- Next supervised work: A should analyze the losing `601929` breakout samples, especially wide support distance and opening-gap buckets. B should propose at most one minimal guard, and C must rerun the same 10-stock pool before any promotion discussion.

## v029 Supervision Update

- User identified the next bottleneck after v028: the breakout candidate is still too narrow, and the losing `601929` samples suggest the breakout cluster needs internal entry guards, especially support distance and opening gap.
- Worker A analysis: `019f3f90-f8df-7913-afc4-c86bebf301fc`; completed read-only. It found that `601929` losses included `gap +3.01%` on `2025-08-15`, and extreme support distance around `10.71%` and `9.91%` on `2025-11-05` and `2026-05-20`.
- Worker B solution: `019f3f91-24bf-7050-a114-1b5a0eda353f`; completed read-only. It confirmed the minimal implementation point is `TradeDiscipline.confirm_volume_probe_opening()` and that `volume_probe.py` / `replay.py` do not need changes.
- Supervisor correction: do not hard-block every `support_distance > 5%`, because same-run evidence shows wide-support breakout buckets also contain major winners. The implemented guard is narrower: block `gap > 3.0%`, and block `support_distance > 8.0%` only when `gap < 0.5%`.
- Supervisor/C implementation completed in `src/wealth_lab/trade_discipline.py`, `src/wealth_lab/training.py`, `tests/test_volume_probe.py`, and `tests/test_training.py`.
- Trading behavior changed: yes, but only for the new experimental candidate `volume_price_breakout_opening_guard_probe`. v028 `volume_price_breakout_follow_through_probe` remains in the candidate list unchanged as the same-run control.
- Targeted test result: `python -m pytest tests\test_volume_probe.py tests\test_training.py -q` => `47 passed`.
- Full test result: `python -m pytest -q` => `94 passed`.
- Final training artifacts: `runtime/training/20260708T023826Z-summary.md` and `runtime/training/20260708T023826Z-training.jsonl`.
- Same-run v028 control: `volume_price_breakout_follow_through_probe` had `9` closed trades across `4` traded symbols, `5.57%` average expectancy, `0.21%` average return, and `0.20%` average max drawdown.
- New v029 candidate result: `volume_price_breakout_opening_guard_probe` had `6` closed trades across `4` traded symbols, `11.12%` average expectancy, `0.27%` average return, and `0.06%` average max drawdown.
- `601929` result improved from v028 `4` closed trades / `-0.20%` return / `1.44%` max drawdown / `-2.39%` expectancy to v029 `1` closed trade / `0.45%` return / `0.06%` max drawdown / `7.06%` expectancy.
- Supervisor decision: do not promote. v029 removes the identified `601929` loss cluster and improves quality metrics, but closed trades fall from `9` to `6`; the candidate is still far below the `30` closed-trade promotion gate and does not solve coverage.
- Next supervised work: stop tightening the same breakout guard. A should analyze why the remaining six v029 breakout trades were acceptable, especially the wide-support winners in `000592` and `600879`; B should propose one way to expand high-quality breakout coverage without lowering the entry discipline; C must show no further trade-count regression.

## v030 Supervision Update

- User identified the next bottleneck after v029: the strategy is becoming a cautious filter, not a trader that finds more high-quality breakouts. The requested experiment was confirmation-entry: signal day observes, next day verifies承接, then buy at the following open.
- Worker A analysis: `019f3fa2-f573-7a92-8d94-26dd7709f5a3`; completed read-only. It confirmed `breakout_start:volume_node:volume_breakout` was the strongest v029 structure at `2` trades / `100%` win rate / `27.91%` average return, while `breakout_start:accumulation_watch` was mixed and should not be bought directly.
- Worker B solution: `019f3fa3-2214-79d3-9aa9-2f67476f9cf3`; completed read-only. It recommended adding a separate replay pending-observation state so v028/v029 immediate-buy behavior stays unchanged.
- Worker C test work: `019f3fa3-4691-7f33-83bc-905829016a00`; completed. It added replay/training tests first, which initially exposed the expected missing production config and candidate registration.
- Supervisor/C implementation completed in `src/wealth_lab/trade_discipline.py`, `src/wealth_lab/replay.py`, `src/wealth_lab/training.py`, `tests/test_volume_probe.py`, and `tests/test_training.py`.
- Trading behavior changed: yes, but only for the new experimental candidate `volume_price_breakout_confirmation_entry_probe`. v028 and v029 candidates remain available as same-run controls.
- Execution discipline added:
  - Signal day breakout trial writes an observation record instead of buying immediately.
  - The next bar must confirm price, support, volume-state, and main-flow conditions.
  - A confirmed observation becomes a normal pending buy for the following open.
  - `shrink_pullback`, `quiet_consolidation`, and `dry_up_base` remain blocked for this breakout experiment.
- Targeted test result: `python -m pytest tests\test_volume_probe.py tests\test_training.py -q` => `49 passed`.
- Full test result: `python -m pytest -q` => `96 passed`.
- Final training artifacts: `runtime/training/20260708T030427Z-summary.md` and `runtime/training/20260708T030427Z-training.jsonl`.
- Same-run v028 control: `volume_price_breakout_follow_through_probe` had `9` closed trades across `4` traded symbols, `5.57%` average expectancy, `0.21%` average return, and `0.20%` average max drawdown.
- Same-run v029 control: `volume_price_breakout_opening_guard_probe` had `6` closed trades across `4` traded symbols, `11.12%` average expectancy, `0.27%` average return, and `0.06%` average max drawdown.
- New v030 candidate result: `volume_price_breakout_confirmation_entry_probe` had `1` closed trade across `1` traded symbol, `1.52%` average expectancy, `0.02%` average return, and `0.00%` average max drawdown.
- Promotion gate result: `OBSERVE`, reason `needs at least 30 closed trades; got 1`.
- Supervisor decision: do not promote. v030 failed as an expansion experiment because it reduced coverage from v029 `6` trades to `1` trade and missed the strongest `000592` / `600879` style breakout winners.
- Next supervised work: A should analyze why confirmation-entry misses the strong direct-breakout samples; B should propose a split rule that preserves direct probing for strong `volume_node:volume_breakout` but keeps weaker `accumulation_watch` in observation, or recommend broader pool/time validation if sample size is the real bottleneck; C must not accept any change that reduces closed trades below v029 or fails the no-regression improvement gate.

## v031 Supervision Update

- User requested expanding the pool from 10 stocks to 100-300 random non-ChiNext A-shares and requiring every strategy to report capital utilization, filtered buy signals, top filter condition, and missed big-move attribution.
- Supervisor/C implementation completed in `src/wealth_lab/stock_pool.py`, `src/wealth_lab/cli.py`, `src/wealth_lab/providers/efinance_provider.py`, `src/wealth_lab/training.py`, `tests/test_stock_pool.py`, and `tests/test_training.py`.
- Trading behavior changed: no. v031 changes stock-pool selection, diagnostics, reporting, and promotion gates only.
- Random pool behavior: `train-replay --random-pool-size N --random-seed S` selects from current efinance A-share spot quotes, excludes `300/301` by default, and is reproducible by seed.
- Targeted test result: `python -m pytest tests\test_stock_pool.py tests\test_training.py -q` => `15 passed`.
- Full test result: `python -m pytest -q` => `100 passed`.
- Completed 100-stock evidence source: `runtime/training/20260708T032635Z-summary.md` and `runtime/training/20260708T032635Z-training.jsonl`.
- v031 retrospective utilization report: `runtime/training/20260708T032635Z-v031-utilization-review.md`.
- Fresh v031 random-pool rerun note: efinance full-market quote fetch failed once with remote disconnect, and the explicit same-pool rerun stalled without output; both were treated as data-source execution issues, not strategy evidence.
- Revised promotion decision: `volume_price_breakout_follow_through_probe` is no longer promotable. It has `32` closed trades and `3.14%` average expectancy, but only `0.06%` average return, `0.39%` holding utilization, and `0.02%` average position.
- Revised utilization evidence:
  - `volume_price_breakout_follow_through_probe`: `92 / 23418` symbol-days invested, `23326` symbol-days cash, qualified filtered buy signals `8478`, ordinary non-signal days `15139`.
  - `volume_price_breakout_opening_guard_probe`: `81 / 23418` symbol-days invested, average position `0.02%`, still below the `30` closed-trade gate with `28` trades.
  - `volume_price_quiet_exception_flow_guard_probe`: `443` closed trades and `1.89%` holding utilization, but average expectancy is only `0.18%`, below the `0.50%` cost/slippage buffer.
- Supervisor decision: do not promote any candidate. v031 validates the user's concern that low annual return is partly a capital-utilization problem, not just a buy/sell trigger problem.
- Next supervised work: A should analyze why missed big moves are mostly ordinary non-signal days, B should propose a way to expand high-quality recognition without relaxing failed clusters, and C must prove any change improves return without reducing utilization discipline.
## v032 Supervision Update

- User requested keeping `volume_price_breakout_opening_guard_probe` as the current main strategy baseline and explicitly not adding more confirmation conditions.
- Supervisor/C implementation completed in `src/wealth_lab/training.py` and `tests/test_training.py`.
- Trading behavior changed: no. This update adds missed-opportunity diagnostics only.
- Diagnostic correction:
  - A signal-day `BUY` intent is no longer enough to exclude a missed opportunity.
  - If the next open is canceled by `opening_guard` and no `BUY` fill occurs, the missed big move is counted and attributed to `opening_guard_cancel`.
  - Missed opportunities now carry exact attribution counts and capped detail rows for `volume_price_breakout_opening_guard_probe`.
- Full test result: `python -m pytest -q` => `101 passed`.
- Final training artifacts: `runtime/training/20260708T055337Z-summary.md` and `runtime/training/20260708T055337Z-training.jsonl`.
- Same-pool result for `volume_price_breakout_opening_guard_probe`:
  - `99` valid symbol results, `1` data error.
  - `30` closed trades across `18` traded symbols.
  - `20` wins, `10` losses, `0` flats; win rate `66.67%`.
  - Average account return `0.07%`; average closed-trade expectancy `5.39%`.
  - Holding utilization `0.36%`; average position `0.02%`.
- Missed big-move attribution:
  - Total missed large forward-move nodes: `1986`.
  - Filtered or guarded: `631`; ordinary non-signal: `1355`; unrecognized: `0`.
  - Exact categories: `ordinary_non_signal=1355`, `not_volume_breakout=498`, `history_gate_failed=114`, `opening_guard_cancel=16`, `other_filtered_signal=3`.
- Supervisor decision: do not promote. The baseline now has enough closed trades to touch the `30` trade floor, but the average account return and capital utilization remain far below the 10% annual target. The next work should analyze recognition gaps in `ordinary_non_signal` and `not_volume_breakout`, not add more guards to opening entry.

## v033 Supervision Update

- User requested deleting the other strategies.
- Supervisor/C implementation completed in `src/wealth_lab/training.py`, `tests/test_training.py`, and `README.md`.
- Trading behavior changed: no change to `volume_price_breakout_opening_guard_probe` buy/sell rules. The default candidate pool changed.
- Default candidate pool now contains exactly one strategy:
  - `volume_price_breakout_opening_guard_probe`
  - tier: `core`
- Archived research candidates remain in `_legacy_training_candidates()` for old-run comparison and provenance, but `run_replay_training()` no longer uses them by default.
- Verification:
  - `python -m pytest tests\test_training.py -q` => `13 passed`.
  - `python -m pytest -q` => `101 passed`.
  - Direct probe returned one default candidate: `['volume_price_breakout_opening_guard_probe']`.
- Supervisor decision: this is a scope-control change, not a promotion proof. Future training runs should be interpreted as the single-strategy baseline unless explicit custom candidates are passed in code.
