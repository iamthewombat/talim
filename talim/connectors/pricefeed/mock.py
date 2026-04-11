"""Mock price feed — replays bars from a DataFrame or Parquet file.

Critical for testing and backtesting. The interface mirrors the live feed
so the same code runs in both contexts.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from talim.connectors.pricefeed.base import BasePriceFeed
from talim.models.bar import OHLCVBar


class MockPriceFeed(BasePriceFeed):
    """Replays OHLCV bars from a DataFrame or Parquet file."""

    def __init__(
        self,
        source: pd.DataFrame | Path | str | None = None,
        instrument: str = "ES",
        timeframe: str = "5m",
    ):
        super().__init__()
        self._instrument = instrument
        self._timeframe = timeframe
        self._df: pd.DataFrame | None = None
        if source is not None:
            self.load(source)

    def load(self, source: pd.DataFrame | Path | str) -> None:
        """Load bars from a DataFrame, Parquet file path, or CSV path."""
        if isinstance(source, pd.DataFrame):
            self._df = source.copy()
        else:
            path = Path(source)
            if not path.exists():
                raise FileNotFoundError(f"Price data file not found: {path}")
            if path.suffix == ".parquet":
                self._df = pd.read_parquet(path)
            elif path.suffix == ".csv":
                self._df = pd.read_csv(path)
            else:
                raise ValueError(f"Unsupported file type: {path.suffix}")

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def subscribe(self, instrument: str) -> None:
        self._subscribed.add(instrument)

    def _row_to_bar(self, row: pd.Series) -> OHLCVBar:
        ts = row.get("timestamp")
        if isinstance(ts, pd.Timestamp):
            ts = ts.to_pydatetime()
        elif isinstance(ts, str):
            ts = datetime.fromisoformat(ts)
        elif ts is None:
            ts = datetime.now(tz=timezone.utc)

        return OHLCVBar(
            instrument=self._instrument,
            timestamp=ts,
            open=float(row["open"]),
            high=float(row["high"]),
            low=float(row["low"]),
            close=float(row["close"]),
            volume=float(row["volume"]),
            timeframe=self._timeframe,
        )

    def replay(self) -> list[OHLCVBar]:
        """Replay all loaded bars, emitting each to registered callbacks.

        Returns the list of emitted bars.
        """
        if self._df is None:
            raise RuntimeError("No data loaded. Call load() first.")
        if not self._connected:
            self.connect()

        bars: list[OHLCVBar] = []
        for _, row in self._df.iterrows():
            bar = self._row_to_bar(row)
            bars.append(bar)
            self._emit(bar)
        return bars
