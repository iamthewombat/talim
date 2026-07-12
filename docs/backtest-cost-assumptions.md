# Backtest Cost Assumptions (BR-05 / WP-86)

Standardised fees/spread/slippage assumptions for Talim backtests, so results
across strategies, timeframes, and sessions are comparable and stop
overstating edge on spread-quoted CFD venues.

## Model

The on_bar engine (`talim/backtest/engine.py`) treats bar data as **mid**
prices and applies costs per fill via `BacktestCostConfig`
(`talim/backtest/costs.py`):

- **Spread** — each fill pays half of `spread_points`: buys fill at
  `mid + spread/2`, sells at `mid - spread/2`. A round trip pays the full
  spread once.
- **Slippage** — `slippage_points` extra adverse points per fill, on top of
  the half-spread. One conservative knob covering both entries and
  stop/target exits.
- **Commission** — `commission_per_side` flat account-currency per fill,
  times quantity, subtracted from trade PnL. Zero for the current
  spread-only index CFDs; the knob exists for future commission venues.

Position sizing still uses the raw signal entry/stop (mirroring live intent);
only fills and PnL are cost-adjusted.

## Standard values

Values live in `config/backtest_costs.json`, keyed by venue then canonical
instrument id. They are **conservative desk assumptions** derived from
advertised broker minimum spreads plus a margin for off-peak widening — they
are deliberately slightly worse than best-case advertised spreads.

Proxy datasets (`dukascopy-proxy`) charge the costs of the venue we would
actually trade on (FOREX.com), because proxy backtests exist to predict live
venue results, not Dukascopy's own trading costs.

### Verification checklist (before treating values as final)

The assumptions must be validated against live demo quotes. This needs broker
credentials, so it is a deploy-host task:

1. During the instrument's liquid session, snapshot bid/ask from the
   FOREX.com and IG demo quote endpoints every minute for at least an hour.
2. Repeat once during the off-peak session (e.g. SYCOM for AU200).
3. Compare observed median and p90 spread against `spread_points`; bump the
   config if p90 exceeds it.
4. Record the observation date in the config `notes`.

## Usage

```bash
# Standard costed run (recommended default for all comparisons):
python scripts/run_backtest.py --strategy momentum-US500 --instrument US500.cash \
  --timeframe 5m --data-dir data/forexcom --costs-venue forexcom

# Explicit frictionless run (prints a warning):
python scripts/run_backtest.py --strategy momentum-US500 --instrument US500.cash \
  --timeframe 5m --data-dir data/forexcom
```

Programmatic use:

```python
from talim.backtest.costs import load_cost_config
from talim.backtest.engine import run_backtest

costs = load_cost_config("forexcom", "US500.cash")
results = run_backtest("momentum-US500", instrument="US500.cash",
                       timeframe="5m", data_dir="data/forexcom", costs=costs)
```

Unknown venues/instruments fail loudly (same philosophy as the WP-73
data-loader hardening) — a typo cannot silently produce a frictionless
backtest.

## Known limitations

- **Overnight financing is not modelled.** The engine simulates single
  round-trip trades without tracking hold time in days. Live P&L models
  financing (WP-52); backtests assume short-hold intraday behaviour. If a
  strategy starts holding multi-day, revisit this before trusting results.
- **The vectorbt fast path stays frictionless.** `vectorbt_engine.py` is a
  parameter-sweep/parity tool; adding a different cost model there would
  drift from the on_bar engine. Rank sweeps frictionless, then confirm
  finalists with costed on_bar runs.
- **Stops fill at `stop ± slippage`.** Real fast-market stop fills can be
  worse than one standard slippage increment. The values chosen are
  averages, not tail cases.
- **Existing recorded baselines** (`docs/backtest-baselines/`) were captured
  frictionless before WP-86. Re-baseline with `--costs-venue` before
  comparing costed runs against them (see
  `docs/backtest-comparison-rules.md`).
