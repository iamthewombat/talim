"""Binance price feed via ccxt.pro WebSocket.

Lightweight wrapper around ccxt.pro.binance for streaming OHLCV bars.
Actual WS streaming requires running an asyncio loop; this module provides
the connector scaffold. Integration with live Binance requires network access.
"""

from __future__ import annotations

from talim.connectors.pricefeed.base import BasePriceFeed
from talim.connectors.pricefeed.normaliser import normalise_binance_kline
from talim.models.bar import OHLCVBar


class BinancePriceFeed(BasePriceFeed):
    """Binance WebSocket price feed via ccxt.pro."""

    def __init__(self, timeframe: str = "5m", sandbox: bool = False):
        super().__init__()
        self._timeframe = timeframe
        self._sandbox = sandbox
        self._client = None

    def connect(self) -> None:
        """Initialise the ccxt.pro client."""
        try:
            import ccxt.pro as ccxtpro  # type: ignore
        except ImportError as e:
            raise ImportError(
                "ccxt.pro required for BinancePriceFeed. Install with: pip install ccxtpro"
            ) from e

        self._client = ccxtpro.binance({"enableRateLimit": True})
        if self._sandbox:
            self._client.set_sandbox_mode(True)
        self._connected = True

    def disconnect(self) -> None:
        if self._client is not None:
            # ccxt.pro clients need close() to release sockets
            try:
                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.ensure_future(self._client.close())
                else:
                    loop.run_until_complete(self._client.close())
            except Exception:
                pass
        self._connected = False

    def subscribe(self, instrument: str) -> None:
        """Add an instrument (e.g. 'BTC/USDT') to the subscription set."""
        self._subscribed.add(instrument)

    async def watch_once(self, instrument: str) -> OHLCVBar:
        """Await a single bar from Binance for the given instrument.

        Returns the normalised OHLCVBar.
        """
        if self._client is None:
            self.connect()
        ohlcv = await self._client.watch_ohlcv(instrument, self._timeframe)  # type: ignore[union-attr]
        latest = ohlcv[-1] if isinstance(ohlcv, list) and ohlcv else ohlcv
        bar = normalise_binance_kline(latest, instrument=instrument, timeframe=self._timeframe)
        self._emit(bar)
        return bar
