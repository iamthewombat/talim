# Baseline Comparison Rules (BR-04 / WP-87) — PROPOSAL

> Status: **draft for Justin's sign-off**. These rules formalise how we decide
> whether a strategy/parameter change is an improvement. Nothing here is
> enforced in code yet; once approved, the acceptance gates can be encoded
> into the backtest history/comparison tooling.

## Why

Ad-hoc backtest comparisons drift: different data windows, sizing, costs, or
metrics make "it looks better" meaningless. These rules pin down what a valid
comparison is and what counts as an improvement.

## 1. Valid comparison preconditions

Two backtest runs are comparable only if **all** of these match:

| Dimension | Rule |
|-----------|------|
| Instrument + timeframe | Identical (`US500.cash` 5m vs 5m, never 5m vs 1h) |
| Data source + window | Identical parquet source dir and period (same `period_start`/`period_end`) |
| Price type | Identical (MID vs MID; never mix BID/ASK/MID) |
| Sizing config | Identical `BacktestSizingConfig` (document mode + params) |
| Cost config | Identical `BacktestCostConfig`; costed runs (`--costs-venue`) are the standard — frictionless runs are for debugging only |
| Engine | on_bar engine for decisions; vectorbt only for sweeps/screening |

The backtest history DB (`backtest_runs`) records most of these; comparisons
should cite run ids.

## 2. Baseline definition

- Each strategy × instrument × timeframe has **one current baseline**: the
  default-params costed run recorded in `docs/backtest-baselines/` (JSON) and
  the backtest history DB.
- Existing baselines (`us500-2026-04-19.json`, AU200 baseline) predate the
  WP-86 cost model and are frictionless. **First action after these rules are
  approved: re-record all baselines with standard costs** and mark the old
  files superseded.
- Re-baselining happens only when: data coverage materially extends, cost
  assumptions change, or a param change is accepted as the new default.
  Each re-baseline updates the JSON, cites the history run id, and notes why.

## 3. Minimum validity thresholds

A run is **inadmissible** (neither improvement nor regression evidence) if:

- `total_trades < 30` on the comparison window, or
- the data window spans less than ~3 months for 1h+ timeframes or ~3 weeks
  for 5m, or
- the run warns of zero trades / missing data.

Inadmissible runs can still guide exploration; they cannot change a default.

## 4. What counts as an improvement

A candidate beats the baseline when, on the same comparison window:

1. **Primary:** Sharpe ratio improves by at least **+10% relative**, and
2. **Guardrail:** max drawdown does not worsen by more than **10% relative**,
   and
3. **Guardrail:** total trades stays ≥ 30 and does not collapse below **half**
   the baseline's trade count (a "better" Sharpe from 6 lucky trades is
   cherry-picking), and
4. **Tiebreak/secondary:** profit factor and win rate are reported but do not
   gate.

If Sharpe improves but a guardrail fails, the change is a judgement call —
flag it for Justin rather than auto-accepting.

## 5. Overfitting hygiene

- Parameter sweeps must reserve a **holdout segment** (most recent ~25% of the
  window). Improvements must hold on the holdout, not just the sweep segment.
- A param change accepted from a sweep should be re-run on at least one other
  instrument or timeframe where the strategy is active, as a sanity check —
  large unexplained divergence is a red flag.
- Walk-forward analysis is a future upgrade (out of scope for this proposal).

## 6. Recording

Every accepted change gets:

- a backtest history run id pair (baseline id, candidate id),
- an updated baseline JSON in `docs/backtest-baselines/`,
- a PROGRESS.md session-log row noting the change and the numbers.

## Open questions for Justin

1. Are +10% relative Sharpe / -10% max-DD guardrails the right starting
   gates, or should absolute floors (e.g. Sharpe ≥ 0.1) also apply?
2. Should the standard comparison window be "all available data" or a fixed
   rolling window (e.g. last 2 years) once Dukascopy deep history lands?
3. Minimum trade count 30 — acceptable, or raise for 5m timeframes?
