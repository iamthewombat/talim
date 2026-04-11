# mean-reversion-ES

## Overview
Bollinger Band mean-reversion strategy for E-mini S&P 500 futures (ES).

## Logic
- **Entry long:** Price closes below lower Bollinger Band (cross from above)
- **Entry short:** Price closes above upper Bollinger Band (cross from below)
- **Stop:** 2.0x ATR(14) from entry
- **Target:** 1.5x ATR(14) from entry (tighter target, higher win rate expected)

## Parameters
| Parameter | Default | Description |
|-----------|---------|-------------|
| bb_period | 20 | Bollinger Band lookback period |
| bb_std | 2.0 | Number of standard deviations |
| atr_multiplier_stop | 2.0 | ATR multiple for stop loss |
| atr_multiplier_target | 1.5 | ATR multiple for profit target |

## Regime Suitability
Best suited for **mean_reversion** and **low_vol** range-bound regimes. Consider disabling during strong **momentum** regimes.

## Risk Notes
- Max 2 contracts per signal
- Avoid during high-impact news events
