"""IG CFD price feed using REST bars plus optional snapshot aggregation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx

from talim.cfd import CfdInstrumentRegistry, load_default_registry
from talim.connectors.exchange.ig_discovery import (
    IgCredentials,
    IgDiscoveryClient,
    IgDiscoveryError,
)
from talim.connectors.pricefeed.base import BasePriceFeed
from talim.connectors.pricefeed.normaliser import (
    PriceSnapshot,
    SnapshotBarBuilder,
    normalise_ig_price_bar,
    normalise_ig_snapshot,
)
from talim.models.bar import OHLCVBar


IG_RESOLUTION_MAP = {
    "1m": "MINUTE",
    "2m": "MINUTE_2",
    "3m": "MINUTE_3",
    "5m": "MINUTE_5",
    "10m": "MINUTE_10",
    "15m": "MINUTE_15",
    "30m": "MINUTE_30",
    "1h": "HOUR",
    "2h": "HOUR_2",
    "4h": "HOUR_4",
    "1d": "DAY",
}


class IgPriceFeed(IgDiscoveryClient, BasePriceFeed):
    """REST-driven IG price feed for canonical CFD instruments."""

    def __init__(
        self,
        credentials: IgCredentials,
        *,
        timeframe: str = "5m",
        registry: CfdInstrumentRegistry | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        BasePriceFeed.__init__(self)
        IgDiscoveryClient.__init__(self, credentials, client=client)
        if timeframe not in IG_RESOLUTION_MAP:
            raise ValueError(
                f"unsupported IG timeframe {timeframe!r}; "
                f"expected one of {sorted(IG_RESOLUTION_MAP)}"
            )
        self._timeframe = timeframe
        self._registry = registry or load_default_registry()
        self._last_emitted: dict[str, datetime] = {}
        self._builder = SnapshotBarBuilder(timeframe=timeframe)

    @classmethod
    def from_env(
        cls,
        *,
        timeframe: str = "5m",
        registry: CfdInstrumentRegistry | None = None,
        client: httpx.Client | None = None,
    ) -> "IgPriceFeed":
        return cls(
            IgCredentials.from_env(),
            timeframe=timeframe,
            registry=registry,
            client=client,
        )

    def connect(self) -> None:
        self.create_session()
        self._connected = True

    def disconnect(self) -> None:
        self.close()
        self._connected = False

    def subscribe(self, instrument: str) -> None:
        self._registry.get(instrument)
        self._subscribed.add(instrument)

    def prime_history(self, instrument: str, min_bars: int = 50) -> list[OHLCVBar]:
        bars = self.fetch_bars(instrument, page_size=max(1, min_bars))
        emitted: list[OHLCVBar] = []
        for bar in bars:
            if self._should_emit(instrument, bar):
                self._emit(bar)
                emitted.append(bar)
        return emitted

    def poll_once(self, instrument: str) -> OHLCVBar | None:
        bars = self.fetch_bars(instrument, page_size=2)
        if not bars:
            return None
        latest = bars[-1]
        if not self._should_emit(instrument, latest):
            return None
        self._emit(latest)
        return latest

    def poll_snapshot_once(self, instrument: str) -> OHLCVBar | None:
        snapshot = self.fetch_snapshot(instrument)
        bar = self._builder.ingest(snapshot)
        if bar is None:
            return None
        if not self._should_emit(instrument, bar):
            return None
        self._emit(bar)
        return bar

    def fetch_bars(
        self,
        instrument: str,
        page_size: int = 50,
        page_number: int = 1,
    ) -> list[OHLCVBar]:
        self._ensure_connected()
        payload = self._fetch_prices_payload(
            instrument,
            page_size=page_size,
            page_number=page_number,
        )
        prices = payload.get("prices", [])
        bars = [
            normalise_ig_price_bar(item, instrument=instrument, timeframe=self._timeframe)
            for item in prices
        ]
        bars.sort(key=lambda bar: bar.timestamp)
        return bars

    def fetch_recent_bars(
        self,
        instrument: str,
        *,
        total_bars: int,
        page_size: int = 200,
    ) -> list[OHLCVBar]:
        """Fetch the most recent N bars using IG's historical numPoints route."""
        if total_bars <= 0:
            return []
        self._ensure_connected()
        epic = self._broker_symbol(instrument)
        response = self._client.get(
            f"/prices/{epic}/{IG_RESOLUTION_MAP[self._timeframe]}/{total_bars}",
            headers=self._headers(authenticated=True, version="2"),
        )
        self._raise_for_status(response, f"fetch IG history for {instrument}")
        payload = response.json()
        bars = [
            normalise_ig_price_bar(
                item,
                instrument=instrument,
                timeframe=self._timeframe,
            )
            for item in payload.get("prices", [])
        ]
        bars.sort(key=lambda bar: bar.timestamp)
        return bars[-total_bars:]

    def fetch_snapshot(self, instrument: str) -> PriceSnapshot:
        self._ensure_connected()
        epic = self._broker_symbol(instrument)
        response = self._client.get(
            f"/markets/{epic}",
            headers=self._headers(authenticated=True, version="3"),
        )
        self._raise_for_status(response, f"fetch IG market snapshot for {instrument}")
        payload = response.json()
        snapshot = payload.get("snapshot", {})
        update_time = snapshot.get("updateTime")
        timestamp = self._snapshot_timestamp(update_time)
        return normalise_ig_snapshot(payload, instrument=instrument, timestamp=timestamp)

    def _ensure_connected(self) -> None:
        if not self.is_connected:
            self.connect()

    def _fetch_prices_payload(
        self,
        instrument: str,
        *,
        page_size: int,
        page_number: int,
    ) -> dict[str, Any]:
        epic = self._broker_symbol(instrument)
        response = self._client.get(
            f"/prices/{epic}",
            params={
                "resolution": IG_RESOLUTION_MAP[self._timeframe],
                "max": page_size,
                "pageSize": page_size,
                "pageNumber": page_number,
            },
            headers=self._headers(authenticated=True, version="3"),
        )
        self._raise_for_status(response, f"fetch IG prices for {instrument}")
        return response.json()

    def _broker_symbol(self, instrument: str) -> str:
        mapping = self._registry.resolve_mapping(instrument, "ig")
        if not mapping.broker_symbol:
            raise IgDiscoveryError(f"instrument {instrument!r} has no resolved IG symbol")
        return mapping.broker_symbol

    def _should_emit(self, instrument: str, bar: OHLCVBar) -> bool:
        last = self._last_emitted.get(instrument)
        if last is not None and bar.timestamp <= last:
            return False
        self._last_emitted[instrument] = bar.timestamp
        return True

    @staticmethod
    def _snapshot_timestamp(update_time: str | None) -> datetime:
        now = datetime.now(tz=timezone.utc)
        if not update_time:
            return now
        try:
            hour, minute, second = (int(part) for part in update_time.split(":"))
        except ValueError:
            return now
        return now.replace(hour=hour, minute=minute, second=second, microsecond=0)
