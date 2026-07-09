# Monthly 8% Target Agent Plan

## 1. Objective

- Target: average monthly return reaches 8%.
- Current baseline strategy: `volume_price_breakout_opening_guard_probe`.
- Boundary: the baseline remains a high-risk small-pool reference; no parameter tuning before large-pool evidence passes gates.
- Stock universe constraint: exclude ChiNext `300/301`; random-pool spot price must be `<= 20`.
- Execution gate: a profile combination can enter execution review only after `30+` closed trades, positive expectancy, and win rate clearly above the current large-pool baseline `32.56%`.

Monthly 8% is a research target, not a promotion shortcut. A candidate that reaches the return target through one or two large winners, missing data, or excessive drawdown stays in `OBSERVE`.

## 2. Current Baseline Evidence

- Source summary: `runtime/training/20260709T031838Z-summary.md`
- Source ledger: `runtime/training/20260709T031838Z-trade-ledger.csv`
- Initial cash per isolated symbol replay: `100000.00`
- Processed symbols: `550`
- Valid symbols: `444`
- Training errors: `106`
- Closed trades: `129`
- Wins / losses: `42 / 87`
- Win rate: `32.56%`
- Average closed-trade expectancy: `-1.34%`
- Average winning trade: `4.17%`
- Average losing trade: `-3.99%`
- Average holding days: `3.29`
- Best trade: `20260709T031838Z-600730-002`, `15.33%`
- Worst trade: `20260709T031838Z-603222-001`, `-19.73%`
- Fund-flow coverage: `44.89%`
- No-fund-flow symbols: `37`

Decision: this baseline is not eligible for promotion. It is the reference for diagnosing where the model loses, where it misses opportunities, and which profile combinations deserve further observation.

## 3. Agent Assignments

### Data Quality Agent

Owner: stock pool validity and data coverage.

Tasks:
- Verify random pool excludes ChiNext unless explicitly enabled.
- Verify `--max-price 20` is enforced by quote universe selection.
- Confirm 100/300/1000 pools have enough valid non-ChiNext symbols after provider errors.
- Classify training errors by provider/data/replay root cause.
- Report K-line coverage, fund-flow coverage, and symbols with zero fund-flow rows.

Deliverables:
- `runtime/training/<run_id>-data-quality.md`
- valid symbol list
- invalid symbol list
- error classification table

### Large Pool Diagnosis Agent

Owner: no-parameter-change diagnosis.

Tasks:
- Run `large-pool-diagnosis` on the latest JSONL.
- Split wins/losses, stage, fund state, board prefix, exit reason, and missed opportunities.
- Identify loss concentration and missed-opportunity concentration.
- Keep current strategy as baseline only.

Deliverables:
- `runtime/training/<run_id>-training-large-pool-diagnosis.md`
- top losing profiles
- top missed opportunity reasons
- profile combinations that pass or fail the gate

### Profile Statistics Agent

Owner: stock/environment profile layer, statistics only.

Tasks:
- Market environment: run-level and date-level market state.
- Sector heat: sector-level inflow/strength when available.
- Stock liquidity and volatility: amount, turnover, ATR/range proxy.
- Historical false breakout rate: breakout attempts that fail follow-through.
- Fund-flow quality: fund-flow coverage and direction consistency.
- Current volume-price stage: behavior phase, volume node, trade thesis stage.

Rule: this agent must not connect any profile to buy/sell execution.

Deliverables:
- `runtime/training/<run_id>-profile-statistics.md`
- profile combination table: trades, wins, win rate, expectancy, average return, worst trade, max contribution concentration

### Execution Agent

Owner: integration after profile evidence passes.

Tasks:
- Only consume profile combinations marked eligible by Profile Statistics Agent.
- Compare baseline vs profile-filtered execution.
- Report trade count, win rate, expectancy, monthly return, drawdown, holding days, and capital utilization.

Gate:
- `30+` trades
- positive expectancy
- win rate above `32.56%`
- return not dominated by top one or two trades

### Risk Agent

Owner: target feasibility and risk boundary.

Tasks:
- Measure monthly return distribution.
- Measure monthly max drawdown.
- Measure average loss, worst loss, and consecutive losses.
- Flag any route to 8% monthly that requires unacceptable drawdown or concentration.

Suggested red lines:
- Average losing trade should trend toward `-2%` to `-3%`, not current `-3.99%`.
- Worst-trade tail must be reduced from current `-19.73%`.
- Monthly drawdown must be measured before any promotion.

### Report Agent

Owner: decision report.

Required output fields:
- initial cash
- stock pool rule
- valid symbols
- trade id
- buy date
- sell date
- profit/loss
- return
- holding days
- exit reason
- win rate
- expectancy
- monthly return
- max drawdown
- promotion decision

## 4. Immediate Runbook

1. Rebuild a valid 100/300 nested pool with price and board constraints:

```powershell
python run.py validate-expansion --pool-sizes 100 300 --days 370 --initial-cash 100000 --target-annual-return 151.8 --random-seed 20260709 --max-price 20 --workers 4 --use-quote-cache
```

2. Generate fixed large-pool diagnosis from the new JSONL:

```powershell
python run.py large-pool-diagnosis --jsonl runtime\training\<run_id>-training.jsonl --baseline-win-rate 32.56
```

3. Do not wire any profile to execution until the diagnosis shows an eligible combination:

```text
trades >= 30
expectancy > 0
win_rate > 32.56%
not dominated by top winners
```

## 5. Current Blockers

- Old JSONL runs before the latest patch do not contain persisted `trade_details`, so `large-pool-diagnosis` cannot reconstruct full trade ledgers from those JSONL files.
- The separate ledger CSV has trade IDs, buy/sell dates, return, and holding days, but its `profit_loss_amount` field is `not_persisted`.
- Fund-flow coverage in the latest large-pool run is only `44.89%`, too weak to treat profile conclusions as final.
- Existing baseline expectancy is negative, so the next move is diagnosis/profile filtering, not parameter tuning.
