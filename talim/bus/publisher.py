"""Event publisher — writes events to Redis Streams."""

from __future__ import annotations

import redis

from talim.bus.events import BarEvent, RegimeChangeEvent, SignalEvent, TradeEvent

EventType = BarEvent | RegimeChangeEvent | SignalEvent | TradeEvent


class EventPublisher:
    """Publishes events to Redis Streams."""

    def __init__(self, client: redis.Redis):
        self._client = client

    def publish(self, stream_name: str, event: EventType) -> str:
        """Publish an event to a Redis stream.

        Args:
            stream_name: The stream key (e.g. "talim:bars", "talim:signals").
            event: The event to publish.

        Returns:
            The stream entry ID assigned by Redis.
        """
        data = event.to_dict()
        entry_id: str = self._client.xadd(stream_name, data)  # type: ignore[assignment]
        return entry_id
