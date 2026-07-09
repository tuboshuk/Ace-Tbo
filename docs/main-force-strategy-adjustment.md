# Main-Force Strategy Adjustment Notes

## Evidence Base

- Source run: `runtime/training/20260709T045214Z-training.jsonl`
- Pool rule: non-ChiNext by default, `price <= 20`, seed `20260709`
- Valid symbols: `1000`
- Processed symbols: `1388`
- Errors: `388`
- Initial cash per isolated replay: `100000.00`
- Closed trades: `297`
- Wins / losses: `103 / 194`
- Win rate: `34.68%`
- Average closed-trade expectancy: `-0.5815%`
- Net persisted PnL estimate from trade details: `-8060.00`
- Fund-flow coverage: `46.10%`
- No-fund-flow symbols: `60`

This is still an `OBSERVE` dataset. It is useful for strategy diagnosis, not for direct promotion.

## Main-Force Situations Found

### 1. Sustained Outflow / Markdown

- Trades: `146`
- Win rate: `41.78%`
- Expectancy: `-0.0327%`

This group produces many winners but does not keep positive expectancy. It looks like a mixed zone: some stocks are strong enough to rise despite outflow, but the group still includes too many failed breakouts.

Adjustment:
- Do not ban this group globally.
- Require a stronger point-in-time profile before buying: accumulation or markup profile, controlled distribution score, and recent main-flow windows not mostly negative.

### 2. Accumulation + Sustained Inflow

- Trades: `30`
- Win rate: `46.67%`
- Expectancy: `+0.5418%`

This is the only broad profile combination in the 1000-pool run that clears the initial statistical gate:

- `30+` trades
- positive expectancy
- win rate above current baseline `32.56%`

Adjustment:
- Promote this to a research filter, not the default strategy.
- Validate it through a new candidate before any execution-layer adoption.

### 3. Neutral / Mixed Flow

- Trades: `25`
- Win rate: `20.00%`
- Expectancy: `-1.9772%`

This is a weak main-force state. It suggests indecision or noisy participation rather than clean accumulation.

Adjustment:
- Block new buys when profile is neutral and flow windows are mixed or mostly negative.

### 4. Distribution / Failed Breakout

- Trades: `31`
- Win rate: `16.13%`
- Expectancy: `-2.3542%`

This is the clearest avoid zone.

Adjustment:
- New buys should be blocked when the point-in-time profile stage is `distribution_risk` or distribution score is above the configured cap.
- Existing positions should keep fast follow-through exits.

### 5. No Fund-Flow Signal

- Trades: `21`
- Win rate: `33.33%`
- Expectancy: `-1.1429%`

The strategy can trade without fund-flow coverage, but the expectancy is negative in this 1000-pool run.

Adjustment:
- Do not treat missing fund-flow as a valid main-force thesis.
- Keep it available for diagnostics, but profile-gated candidates should block missing main-force profile evidence.

## Buy Strategy Adjustment

Implemented as a research-only candidate:

`volume_price_main_force_profile_filter_probe`

Rules:
- Keep the current `volume_price_breakout_opening_guard_probe` as baseline.
- Still require `volume_breakout`.
- Still use opening guard and support-risk sizing.
- Add main-force profile gate before buying:
  - profile must exist
  - profile stage must be one of:
    - `accumulation_watch`
    - `markup_confirmed`
  - distribution score must be `<= 55`
  - recent main-flow windows must be mostly non-negative

This maps the observed winning broad state, `accumulation + sustained_inflow`, into point-in-time data that can be checked before buying.

## Sell Strategy Adjustment

The research candidate keeps the fast follow-through exit path:

- sell when main flow turns weak after entry
- sell when the breakout thesis invalidates
- sell earlier when there is no follow-through after `2` bars
- sell on profitable high-volume stall
- otherwise max hold remains `5` bars

Reason:
- Losing groups are dominated by failed follow-through, invalidation, and stop-loss tails.
- The current large-pool worst-trade tail is still too large for an 8% monthly objective.

## Current Code Changes

- `src/wealth_lab/trade_discipline.py`
  - Added `enable_volume_price_main_force_profile_filter`.
  - Added point-in-time main-force profile buy blocker.
- `src/wealth_lab/training.py`
  - Added `training_candidates_with_main_force_profile_probe()`.
  - Registered `volume_price_main_force_profile_filter_probe`.
- `src/wealth_lab/cli.py`
  - Added `--include-main-force-profile-probe` for `train-replay`.
  - Added `--include-main-force-profile-probe` for `validate-expansion`.

## Next Validation Command

Run a controlled 100/300 comparison before another 1000 run:

```powershell
python run.py validate-expansion --pool-sizes 100 300 --days 370 --initial-cash 100000 --target-annual-return 96 --random-seed 20260709 --max-price 20 --use-quote-cache --workers 4 --include-main-force-profile-probe
```

Promotion rule for the new candidate:

- candidate closed trades `>= 30`
- candidate expectancy `> 0`
- candidate win rate `> 34.68%`
- candidate average loss improves materially from current `-3.80%` loss average
- no top-one or top-two winner concentration

Until that validation passes, the new filter remains research-only.
