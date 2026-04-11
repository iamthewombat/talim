"""Normalise exchange-specific bar formats to OHLCVBar."""

from __future__ import annotations

from datetime import datetime, timezone

from talim.models.bar import OHLCVBar


def normalise_binance_kline(
    kline: list | dict, instrument: str, timeframe: str = "5m"
) -> OHLCVBar:
    """Convert a Binance kline (websocket or REST) to an OHLCVBar.

    Binance kline REST format (list):
        [open_time, open, high, low, close, volume, close_time, ...]

    Binance kline WS format (dict under 'k'):
        {"t": open_time, "o": open, "h": high, "l": low, "c": close, "v": volume, ...}
    """
    if isinstance(kline, list):
        open_time_ms = int(kline[0])
        open_ = float(kline[1])
        high = float(kline[2])
        low = float(kline[3])
        close = float(kline[4])
        volume = float(kline[5])
    elif isinstance(kline, dict):
        k = kline.get("k", kline)
        open_time_ms = int(k["t"])
        open_ = float(k["o"])
        high = float(k["h"])
        low = float(k["l"])
        close = float(k["c"])
        volume = float(k["v"])
    else:
        raise TypeError(f"Unsupported kline type: {type(kline)}")

    return OHLCVBar(
        instrument=instrument,
        timestamp=datetime.fromtimestamp(open_time_ms / 1000, tz=timezone.utc),
        open=open_,
        high=high,
        low=low,
        close=close,
        volume=volume,
        timeframe=timeframe,
    )
