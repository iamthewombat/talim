# momentum-US500

## Overview
EMA crossover momentum strategy for the US500 index CFD (S&P 500 cash, tradeable via IG/FOREX.com).

## Logic
- **Entry long:** EMA(8) crosses above EMA(21)
- **Entry short:** EMA(8) crosses below EMA(21)
- **Stop:** 1.5x ATR(14) from entry
- **Target:** 3.0x ATR(14) from entry

## Parameters
| Parameter | Default | Description |
|-----------|---------|-------------|
| ema_fast_period | 8 | Fast EMA lookback |
| ema_slow_period | 21 | Slow EMA lookback |
| atr_multiplier_stop | 1.5 | ATR multiple for stop loss |
| atr_multiplier_target | 3.0 | ATR multiple for profit target |

## Regime Suitability
Best suited for **momentum** and **low_vol** trending regimes. Consider disabling during **high_vol** or **mean_reversion** regimes.

## Risk Notes
- Max 2 contracts per signal
- Do not stack signals in same direction
