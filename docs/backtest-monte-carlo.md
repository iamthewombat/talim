# Monte Carlo Robustness (backtest suite)

`scripts/run_monte_carlo.py` applies a stationary block bootstrap
(Politis-Romano, mean block 20 days) to the daily mark-to-market equity
changes of any strategy or multi-leg book, using the exact same simulation
path as `run_portfolio_backtest.py` (same leg specs, costs, windows,
`--entries-start` OOS gating). Math lives in `talim/backtest/monte_carlo.py`;
Sharpe/drawdown definitions match `metrics.compute_equity_metrics`, so
percentiles are directly comparable with scorecard numbers.

## What it is for

- **Drawdown tail for sizing**: `max_dd_pct.p5` (bad tail) instead of the
  single observed path's drawdown. Use this when setting risk-per-trade or
  capital allocation, not the observed DD.
- **Significance on small samples**: `annualised_sharpe.p5` and
  `prob_sharpe_below_0` tell you how much of a result could be path luck —
  essential for OOS windows with few trades.
- **Not for edge validation**: the bootstrap recycles observed days. It
  quantifies dispersion around an edge; it cannot prove the edge exists or
  repair selection bias. Walk-forward OOS remains the judge of edges.

## Standard usage

Run it for every strategy/book that passes the hard scorecard gates
(in-sample AND the OOS validation window), with defaults
(`--sims 2000 --block-days 20 --seed 7`):

```bash
uv run python scripts/run_monte_carlo.py \
  --instrument US500.proxy --timeframe 1d --data-dir data/dukascopy \
  --costs-venue dukascopy-proxy --per-bar-costs --end 2025-01-01 \
  --leg '{"strategy": "ibs-reversion"}'
```

Record in the search log: Sharpe p5/p50/p95, max_dd_pct p5, and
`prob_sharpe_below_0`.

## Diagnostic thresholds (soft, per strategy-search scorecard)

- `prob_sharpe_below_0` should be < 0.05 in-sample for survivors.
- `max_dd_pct.p5` is the number quoted for risk sizing (fixed-qty DD numbers
  are scale-dependent; treat all DD values accordingly).
- Do not tune parameters against MC percentiles — that is the same
  overfitting the anti-tamper rules ban, one level up.

## Reference results (2026-07-18, live 3-leg book: momentum+atr-high /
rsi2+atr-low / ibs ungated, US500.proxy 1d, per-bar costs)

- In-sample (to 2025-01-01): observed Sharpe 0.906; bootstrap p5 0.45 /
  p50 0.89 / p95 1.34; DD p5 −1.5%; P(sharpe<=0) = 0/2000.
- OOS (entries from 2025-01-01): observed Sharpe 1.013; bootstrap p5 0.21 /
  p50 1.02 / p95 1.86; DD p5 −1.2%; P(sharpe<=0) = 2.4%.
