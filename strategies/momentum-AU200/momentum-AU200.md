# momentum-AU200

`momentum-AU200` is the first Australia 200 CFD strategy package for Talim.

## Intent

- Trade directional trend continuation on `AU200.cash` and `AU200.fwd`.
- Keep the logic simple enough that the live scanner and on-bar backtester stay identical.
- Bias toward fewer, cleaner signals rather than high-frequency churn.

## Core Logic

- Fast/slow EMA crossover: `13 / 34`
- ATR-based stop and target: `1.6x / 2.8x`
- Minimum EMA separation filter: skip weak crossovers where the EMA gap is less than `0.12 * ATR`

## Market Assumptions

- Primary venue: `IG AU`
- Canonical instrument: `AU200.cash`
- Baseline validation timeframe: `1h`
- Optional live execution timeframe after warmup: `5m`

## Why 1h First

IG's default API allowance can support a full rolling `360`-day `1h` dataset plus a multi-year `1d` context dataset in one pass. A multi-year `5m` dataset cannot be pulled in one shot under the default allowance, so the initial AU200 validation path uses `1h` for baseline backtests and accumulates `5m` execution history separately over time.

## Tunable Parameters

- `ema_fast_period`
- `ema_slow_period`
- `atr_period`
- `atr_multiplier_stop`
- `atr_multiplier_target`
- `min_ema_gap_atr`

## Initial Operating Rules

- Use Talim's CFD session gate; do not trade outside the canonical AU200 session window.
- Use `max_margin_utilization_pct` as the hard risk cap; do not override for demo soak.
- Start on `AU200.cash` only. Do not run `cash` and `fwd` simultaneously during the first soak.
