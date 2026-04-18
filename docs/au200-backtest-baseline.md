# AU200 Backtest Baseline

Baseline AU200 validation run performed on `2026-04-13` using the new `momentum-AU200` package and IG demo historical data.

## Dataset

- Instrument: `AU200.cash`
- Source: `IG AU` demo historical API
- Data root: `data/ig`
- Baseline profile output:
  - `1h.parquet`: `6146` bars returned by IG
  - `1d.parquet`: `730` bars returned by IG

## Command

```bash
./.venv/bin/python scripts/run_backtest.py \
  --strategy momentum-AU200 \
  --instrument AU200.cash \
  --timeframe 1h \
  --data-dir data/ig \
  --params '{"ema_fast_period": 13, "ema_slow_period": 34}' \
  --params '{"ema_fast_period": 10, "ema_slow_period": 30, "min_ema_gap_atr": 0.10}'
```

## Results

### Variant A

- Params: `ema_fast_period=13`, `ema_slow_period=34`
- Net P&L: `-305.44`
- Sharpe: `-0.353`
- Max drawdown: `-368.78`
- Win rate: `22.7%`
- Trades: `22`

### Variant B

- Params: `ema_fast_period=10`, `ema_slow_period=30`, `min_ema_gap_atr=0.10`
- Net P&L: `-950.49`
- Sharpe: `-0.456`
- Max drawdown: `-1002.81`
- Win rate: `17.9%`
- Trades: `56`

## Interpretation

- The baseline strategy is not ready for live capital.
- The slower `13 / 34` configuration was materially better than the faster variant on this first pass.
- Next work should focus on:
  - parameter sweeps around the slower baseline
  - checking whether `AU200.fwd` behaves differently enough to justify a separate variant
  - comparing `1h` backtest behaviour to the live demo scanner before moving down to `5m`
