"""Compute regime fingerprints from OHLCV bar data.

The fingerprint is a 6-feature vector:
  [0] ADX (14-period) — trend strength
  [1] ATR ratio — current ATR / rolling mean ATR (volatility relative to recent history)
  [2] Trend slope — linear regression slope of close prices (normalised by ATR)
  [3] Realised volatility — std of log returns
  [4] Volume ratio — current volume / rolling mean volume
  [5] Momentum — rate of change of close over the window
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_atr(bars: pd.DataFrame, period: int = 14) -> pd.Series:
    """Compute Average True Range."""
    high = bars["high"]
    low = bars["low"]
    close = bars["close"]
    prev_close = close.shift(1)

    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    return tr.rolling(window=period, min_periods=1).mean()


def compute_adx(bars: pd.DataFrame, period: int = 14) -> pd.Series:
    """Compute Average Directional Index."""
    high = bars["high"]
    low = bars["low"]
    close = bars["close"]
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_close = close.shift(1)

    # True range
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    # Directional movement
    plus_dm = np.where((high - prev_high) > (prev_low - low), np.maximum(high - prev_high, 0), 0)
    minus_dm = np.where((prev_low - low) > (high - prev_high), np.maximum(prev_low - low, 0), 0)

    # Smoothed averages
    atr = pd.Series(tr, index=bars.index).rolling(window=period, min_periods=1).mean()
    plus_di = 100 * pd.Series(plus_dm, index=bars.index).rolling(window=period, min_periods=1).mean() / atr
    minus_di = 100 * pd.Series(minus_dm, index=bars.index).rolling(window=period, min_periods=1).mean() / atr

    # DX and ADX
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, np.nan)
    adx = dx.rolling(window=period, min_periods=1).mean()

    return adx.fillna(0)


def compute_fingerprint(bars: pd.DataFrame) -> np.ndarray:
    """Compute a 6-feature regime fingerprint from OHLCV bars.

    Args:
        bars: DataFrame with columns [open, high, low, close, volume].
              Must have at least 20 rows for meaningful results.

    Returns:
        np.ndarray of shape (6,).
    """
    close = bars["close"].values.astype(float)
    volume = bars["volume"].values.astype(float)
    n = len(close)

    # Feature 0: ADX (trend strength)
    adx_series = compute_adx(bars, period=14)
    feat_adx = adx_series.iloc[-1]

    # Feature 1: ATR ratio (current vs rolling mean)
    atr_series = compute_atr(bars, period=14)
    atr_current = atr_series.iloc[-1]
    atr_mean = atr_series.mean()
    feat_atr_ratio = atr_current / atr_mean if atr_mean > 0 else 1.0

    # Feature 2: Trend slope (normalised by ATR)
    x = np.arange(n, dtype=float)
    x_centered = x - x.mean()
    slope = np.dot(x_centered, close) / np.dot(x_centered, x_centered) if n > 1 else 0.0
    feat_trend_slope = slope / atr_current if atr_current > 0 else 0.0

    # Feature 3: Realised volatility (std of log returns)
    log_returns = np.diff(np.log(np.maximum(close, 1e-10)))
    feat_volatility = float(np.std(log_returns)) if len(log_returns) > 0 else 0.0

    # Feature 4: Volume ratio (recent vs mean)
    lookback = min(5, n)
    vol_recent = volume[-lookback:].mean()
    vol_mean = volume.mean()
    feat_volume_ratio = vol_recent / vol_mean if vol_mean > 0 else 1.0

    # Feature 5: Momentum (rate of change)
    lookback_mom = min(20, n - 1)
    if lookback_mom > 0 and close[-lookback_mom - 1] > 0:
        feat_momentum = (close[-1] - close[-lookback_mom - 1]) / close[-lookback_mom - 1]
    else:
        feat_momentum = 0.0

    return np.array(
        [feat_adx, feat_atr_ratio, feat_trend_slope, feat_volatility, feat_volume_ratio, feat_momentum],
        dtype=np.float64,
    )
