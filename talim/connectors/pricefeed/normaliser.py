"""Normalise exchange-specific bar formats to OHLCVBar."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

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


def normalise_ig_price_bar(
    payload: dict[str, Any],
    *,
    instrument: str,
    timeframe: str = "5m",
) -> OHLCVBar:
    """Convert an IG REST `/prices` entry to an OHLCVBar using midpoint prices."""

    def midpoint(price: dict[str, Any]) -> float:
        bid = price.get("bid")
        ask = price.get("ask")
        last = price.get("lastTraded")
        if bid is not None and ask is not None:
            return (float(bid) + float(ask)) / 2.0
        if last is not None:
            return float(last)
        if bid is not None:
            return float(bid)
        if ask is not None:
            return float(ask)
        raise ValueError("IG price payload missing bid/ask/lastTraded values")

    ts_raw = payload.get("snapshotTimeUTC") or payload.get("snapshotTime")
    if not ts_raw:
        raise ValueError("IG price payload missing snapshot time")
    timestamp = _parse_ig_timestamp(str(ts_raw))

    return OHLCVBar(
        instrument=instrument,
        timestamp=timestamp,
        open=midpoint(payload["openPrice"]),
        high=midpoint(payload["highPrice"]),
        low=midpoint(payload["lowPrice"]),
        close=midpoint(payload["closePrice"]),
        volume=float(payload.get("lastTradedVolume") or 0.0),
        timeframe=timeframe,
    )


@dataclass(frozen=True, slots=True)
class PriceSnapshot:
    """A point-in-time price update suitable for local bar aggregation."""

    instrument: str
    timestamp: datetime
    bid: float
    ask: float
    volume: float = 0.0

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0


class SnapshotBarBuilder:
    """Aggregate price snapshots into OHLCV bars."""

    def __init__(self, timeframe: str = "5m") -> None:
        self._timeframe = timeframe
        self._bucket_minutes = _timeframe_to_minutes(timeframe)
        self._current: dict[str, OHLCVBar] = {}

    def ingest(self, snapshot: PriceSnapshot) -> OHLCVBar | None:
        bucket_start = _floor_timestamp(snapshot.timestamp, self._bucket_minutes)
        current = self._current.get(snapshot.instrument)
        price = snapshot.mid
        if current is None:
            self._current[snapshot.instrument] = OHLCVBar(
                instrument=snapshot.instrument,
                timestamp=bucket_start,
                open=price,
                high=price,
                low=price,
                close=price,
                volume=snapshot.volume,
                timeframe=self._timeframe,
            )
            return None

        if bucket_start == current.timestamp:
            self._current[snapshot.instrument] = OHLCVBar(
                instrument=current.instrument,
                timestamp=current.timestamp,
                open=current.open,
                high=max(current.high, price),
                low=min(current.low, price),
                close=price,
                volume=current.volume + snapshot.volume,
                timeframe=current.timeframe,
            )
            return None

        finished = current
        self._current[snapshot.instrument] = OHLCVBar(
            instrument=snapshot.instrument,
            timestamp=bucket_start,
            open=price,
            high=price,
            low=price,
            close=price,
            volume=snapshot.volume,
            timeframe=self._timeframe,
        )
        return finished

    def flush(self, instrument: str) -> OHLCVBar | None:
        return self._current.pop(instrument, None)


def normalise_ig_snapshot(
    payload: dict[str, Any],
    *,
    instrument: str,
    timestamp: datetime | None = None,
) -> PriceSnapshot:
    """Convert an IG `/markets/{epic}` payload into a price snapshot."""

    snapshot = payload.get("snapshot", payload)
    bid = snapshot.get("bid")
    offer = snapshot.get("offer")
    if bid is None or offer is None:
        raise ValueError("IG market snapshot missing bid/offer")
    ts = timestamp or datetime.now(tz=timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return PriceSnapshot(
        instrument=instrument,
        timestamp=ts,
        bid=float(bid),
        ask=float(offer),
        volume=0.0,
    )


def _parse_ig_timestamp(value: str) -> datetime:
    raw = value.strip()
    if "T" in raw:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)
    dt = datetime.strptime(raw, "%Y/%m/%d %H:%M:%S")
    return dt.replace(tzinfo=timezone.utc)


def _timeframe_to_minutes(timeframe: str) -> int:
    tf = timeframe.strip().lower()
    if tf.endswith("m"):
        return int(tf[:-1])
    if tf.endswith("h"):
        return int(tf[:-1]) * 60
    if tf.endswith("d"):
        return int(tf[:-1]) * 24 * 60
    raise ValueError(f"unsupported timeframe {timeframe!r}; expected Xm, Xh, or Xd")


def _floor_timestamp(timestamp: datetime, minutes: int) -> datetime:
    ts = timestamp.astimezone(timezone.utc)
    if minutes >= 24 * 60:
        day_span = max(1, minutes // (24 * 60))
        day_offset = (ts.toordinal() - 1) % day_span
        floored = ts.replace(hour=0, minute=0, second=0, microsecond=0)
        if day_offset:
            floored = floored - timedelta(days=day_offset)
        return floored
    bucket_minute = (ts.minute // minutes) * minutes
    return ts.replace(minute=bucket_minute, second=0, microsecond=0)
