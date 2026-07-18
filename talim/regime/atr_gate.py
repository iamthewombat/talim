"""ATR volatility-regime gate shared by the backtest engine and live scanner.

The gate compares ATR(14) to its own 100-bar simple average:
'atr-high' allows entries only when ATR is above the average, 'atr-low' only
when below. Constants are fixed on purpose — they are part of the validated
strategy book, not tunables. Warmup bars (either rolling stat still NaN)
never allow entries, in both backtest and live paths.
"""

from __future__ import annotations

import pandas as pd

from talim.models.bar import OHLCVBar

ATR_PERIOD = 14
ATR_AVG_PERIOD = 100
MIN_BARS = ATR_PERIOD + ATR_AVG_PERIOD
VALID_FILTERS = ("atr-high", "atr-low")


def atr_regime_mask(data: pd.DataFrame, regime_filter: str) -> pd.Series:
    """Vectorised boolean entry mask over an OHLCV frame (backtest path)."""
    prev_close = data["close"].shift(1)
    tr = pd.concat(
        [
            data["high"] - data["low"],
            (data["high"] - prev_close).abs(),
            (data["low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    atr = tr.rolling(ATR_PERIOD).mean()
    atr_avg = atr.rolling(ATR_AVG_PERIOD).mean()
    if regime_filter == "atr-high":
        mask = atr > atr_avg
    elif regime_filter == "atr-low":
        mask = atr < atr_avg
    else:
        raise ValueError(
            f"unknown regime_filter {regime_filter!r}; expected one of {VALID_FILTERS}"
        )
    return mask.fillna(False).reset_index(drop=True)


def atr_regime_allows(bars: list[OHLCVBar], regime_filter: str) -> bool:
    """Live-path check: does the latest bar sit in the required regime?

    Fail-closed: returns False while there is not enough history to warm both
    rolling stats (mirrors the backtest mask, where warmup bars are False).
    """
    if len(bars) < MIN_BARS:
        return False
    data = pd.DataFrame(
        {
            "high": [b.high for b in bars],
            "low": [b.low for b in bars],
            "close": [b.close for b in bars],
        }
    )
    return bool(atr_regime_mask(data, regime_filter).iloc[-1])


def parse_regime_filters(raw: str | None) -> dict[str, str]:
    """Parse 'strategy:atr-high,other:atr-low' into {strategy: filter}."""
    filters: dict[str, str] = {}
    if not raw:
        return filters
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if ":" not in item:
            raise ValueError(
                f"invalid regime filter entry {item!r}; expected strategy:filter"
            )
        name, _, filt = item.partition(":")
        name, filt = name.strip(), filt.strip().lower()
        if filt not in VALID_FILTERS:
            raise ValueError(
                f"invalid regime filter {filt!r} for {name!r}; expected one of {VALID_FILTERS}"
            )
        filters[name] = filt
    return filters
