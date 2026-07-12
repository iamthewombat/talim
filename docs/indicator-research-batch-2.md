# Indicator Research Batch 2 (BR-03 / WP-88)

> Status: batch defined 2026-07-12. Implementation is agent-pickable work
> (items 1–4 need no market data or credentials). Evaluation is gated on
> costed baselines being recorded (`scripts/rerecord_baselines.py` on the
> deploy host) and WP-87 comparison-rules sign-off.

## What exists today

- **Live indicator library** (`talim/strategy/indicators/`, WP-71): EMA, SMA,
  Wilder ATR, Wilder RSI, Bollinger, MACD, Stochastic, Donchian — each in
  streaming + vectorised form with parity tests.
- **Research features pipeline** (`talim/features/` + `scripts/build_*_features.py`):
  ATR, Bollinger, EMA, MACD, RSI feature builders plus the support/resistance
  levels table and nearest-level features.
- **ADX** exists only inside `talim/regime/fingerprint.py` — strategies and
  the features pipeline cannot use it.

## Why this batch

Three observed problems drive the selection:

1. **EMA-cross whipsaw.** WP-85 suppresses ranging-regime momentum alerts —
   but only in the *scanner*. Backtests replay `strategy.on_bar` directly, so
   the live system and the backtest see different behaviour, and default-param
   baselines are chop-dominated (negative Sharpe). A strategy-level trend/chop
   filter closes that gap and shows up honestly in backtest metrics.
2. **Rigid exits.** The engine and live strategies exit at fixed stop/target
   only; winners are capped at the initial target even in strong trends.
3. **Bollinger-only mean reversion.** One band model, std-dev based, which
   misbehaves when volatility clusters; no squeeze/expansion signal.

## The batch (priority order)

| # | Indicator | Intended use | Why | Data/creds needed to implement? |
|---|-----------|--------------|-----|-------------------------------|
| 1 | **ADX / DMI** | Strategy-level trend filter for momentum entries (e.g. require ADX ≥ threshold at cross time) | Directly attacks whipsaw where backtests can measure it; maths already exists in the regime fingerprint — port to streaming + vectorised library form | No |
| 2 | **Keltner Channels** | Mean-reversion band alternative + BB/KC squeeze detection | EMA and ATR primitives already exist; ATR-based bands degrade more gracefully than std-dev bands in vol clusters | No |
| 3 | **SuperTrend (ATR trailing)** | Trailing exit for momentum strategies | Addresses fixed stop/target exit rigidity; candidate replacement for the static target on trending entries | No |
| 4 | **Kaufman Efficiency Ratio** | Cheap chop filter (0–1); complements ADX; enables KAMA later if ER earns its keep | Single-pass computation; easy parity tests | No |
| 5 | **Session-anchored VWAP** | Intraday anchor for index CFD entries/exits | Registry already carries per-instrument session windows | **Gated on a volume-quality audit** — FOREX.com/IG bar volume and Dukascopy tick-volume approximations must be checked before trusting any volume-weighted indicator |
| 6 | **OBV / volume delta** | Confirmation feature for the research pipeline | Lowest priority; same volume-quality gate as VWAP | Same gate as #5 |

## Definition of done (per indicator)

1. **Library:** streaming + vectorised implementations in
   `talim/strategy/indicators/` with parity tests (WP-71 pattern).
2. **Features:** a `talim/features/` builder + `scripts/build_*_features.py`
   CLI + tests (existing pipeline pattern), so research datasets pick it up.
3. **Hypothesis:** one sentence, written before evaluation (e.g. "requiring
   ADX(14) ≥ 20 at cross time improves momentum-US500 5m Sharpe ≥ +10%
   without halving trade count").
4. **Evaluation:** costed backtest (`--costs-venue`) against the current
   baseline under the WP-87 gates, on the deploy host's datasets.
5. **Verdict:** keep (promote param into strategy defaults via its own WP) or
   kill — either way, record the run ids and verdict in the PROGRESS.md
   session log.

Steps 1–2 for items 1–4 are agent-pickable now. Step 4 is blocked until
costed baselines exist and WP-87 is signed off.

## Explicitly out of scope for this batch

- Ichimoku, Fibonacci/pivot variants, Heikin-Ashi: no current hypothesis tied
  to an observed Talim problem — revisit in batch 3 if batch 2 filters prove
  out.
- ML-derived features: premature until the plain-indicator feature set and
  comparison discipline are bedded down.

## Decision needed from Justin

- [ ] Approve the batch as listed (agents may start items 1–4)
- [ ] Reorder / add / remove items (edit the table and re-date this doc)
