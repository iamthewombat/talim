"""FOREX.com (StoneX TradingApi) CFD price feed using REST bar history.

Streaming (SignalR via `push.cityindex.com`) is deferred to a later WP; scanner
polling via `poll_once` / `prime_history` is sufficient for the PoC and uses the
same cron cadence already wired for IG.
"""

from __future__ import annotations

from typing import Any

import httpx

from talim.cfd import CfdInstrumentRegistry, load_default_registry
from talim.connectors.exchange.forexcom_discovery import (
    ForexcomCredentials,
    ForexcomDiscoveryClient,
    ForexcomDiscoveryError,
)
from talim.connectors.pricefeed.base import BasePriceFeed
from talim.connectors.pricefeed.normaliser import normalise_forexcom_price_bar
from talim.models.bar import OHLCVBar


# FOREX.com bar history takes (interval, span) — span is the multiplier within
# the interval. For example, interval=MINUTE+span=5 → 5-minute bars.
FOREXCOM_TIMEFRAME_MAP: dict[str, tuple[str, int]] = {
    "1m": ("MINUTE", 1),
    "2m": ("MINUTE", 2),
    "3m": ("MINUTE", 3),
    "5m": ("MINUTE", 5),
    "10m": ("MINUTE", 10),
    "15m": ("MINUTE", 15),
    "30m": ("MINUTE", 30),
    "1h": ("HOUR", 1),
    "2h": ("HOUR", 2),
    "4h": ("HOUR", 4),
    "1d": ("DAY", 1),
}


class ForexcomPriceFeed(ForexcomDiscoveryClient, BasePriceFeed):
    """REST-driven FOREX.com price feed for canonical CFD instruments."""

    def __init__(
        self,
        credentials: ForexcomCredentials,
        *,
        timeframe: str = "5m",
        registry: CfdInstrumentRegistry | None = None,
        client: httpx.Client | None = None,
    ) -> None:
        BasePriceFeed.__init__(self)
        ForexcomDiscoveryClient.__init__(self, credentials, client=client)
        if timeframe not in FOREXCOM_TIMEFRAME_MAP:
            raise ValueError(
                f"unsupported FOREX.com timeframe {timeframe!r}; "
                f"expected one of {sorted(FOREXCOM_TIMEFRAME_MAP)}"
            )
        self._timeframe = timeframe
        self._registry = registry or load_default_registry()
        self._last_emitted_ts: dict[str, float] = {}

    @classmethod
    def from_env(
        cls,
        *,
        timeframe: str = "5m",
        registry: CfdInstrumentRegistry | None = None,
        client: httpx.Client | None = None,
    ) -> "ForexcomPriceFeed":
        return cls(
            ForexcomCredentials.from_env(),
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
        bars = self.fetch_bars(instrument, count=max(1, min_bars))
        emitted: list[OHLCVBar] = []
        for bar in bars:
            if self._should_emit(instrument, bar):
                self._emit(bar)
                emitted.append(bar)
        return emitted

    def poll_once(self, instrument: str) -> OHLCVBar | None:
        bars = self.fetch_bars(instrument, count=2)
        if not bars:
            return None
        latest = bars[-1]
        if not self._should_emit(instrument, latest):
            return None
        self._emit(latest)
        return latest

    def fetch_bars(self, instrument: str, count: int = 50) -> list[OHLCVBar]:
        self._ensure_connected()
        market_id = self._market_id(instrument)
        interval, span = FOREXCOM_TIMEFRAME_MAP[self._timeframe]
        response = self._client.get(
            f"/market/{market_id}/barhistory",
            params={"interval": interval, "span": span, "PriceBars": count},
            headers=self._headers(authenticated=True),
        )
        self._raise_for_status(response, f"fetch FOREX.com bars for {instrument}")
        payload: dict[str, Any] = response.json()
        bars = [
            normalise_forexcom_price_bar(item, instrument=instrument, timeframe=self._timeframe)
            for item in payload.get("PriceBars", [])
        ]
        bars.sort(key=lambda bar: bar.timestamp)
        return bars

    def fetch_bars_before(
        self,
        instrument: str,
        *,
        to_timestamp_utc: int,
        count: int = 4000,
        price_type: str = "MID",
    ) -> list[OHLCVBar]:
        """Fetch completed bars before ``to_timestamp_utc`` using barhistorybefore.

        ``to_timestamp_utc`` is epoch seconds. FOREX.com caps ``maxResults`` at
        4000, so callers that need longer ranges should page backwards by
        passing the earliest returned bar's timestamp as the next ``to`` value.
        """

        self._ensure_connected()
        market_id = self._market_id(instrument)
        interval, span = FOREXCOM_TIMEFRAME_MAP[self._timeframe]
        response = self._client.get(
            f"/market/{market_id}/barhistorybefore",
            params={
                "interval": interval,
                "span": span,
                "toTimestampUTC": to_timestamp_utc,
                "maxResults": min(max(1, count), 4000),
                "priceType": price_type.upper(),
            },
            headers=self._headers(authenticated=True),
        )
        self._raise_for_status(response, f"fetch FOREX.com bars before date for {instrument}")
        payload: dict[str, Any] = response.json()
        bars = [
            normalise_forexcom_price_bar(item, instrument=instrument, timeframe=self._timeframe)
            for item in payload.get("PriceBars", [])
        ]
        bars.sort(key=lambda bar: bar.timestamp)
        return bars

    def _ensure_connected(self) -> None:
        if not self.is_connected:
            self.connect()

    def _market_id(self, instrument: str) -> str:
        mapping = self._registry.resolve_mapping(instrument, "forexcom")
        if not mapping.market_id:
            raise ForexcomDiscoveryError(
                f"instrument {instrument!r} has no resolved FOREX.com market id"
            )
        return mapping.market_id

    def _should_emit(self, instrument: str, bar: OHLCVBar) -> bool:
        last = self._last_emitted_ts.get(instrument)
        bar_ts = bar.timestamp.timestamp()
        if last is not None and bar_ts <= last:
            return False
        self._last_emitted_ts[instrument] = bar_ts
        return True
