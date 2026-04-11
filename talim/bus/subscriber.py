"""Event subscriber — reads events from Redis Streams using consumer groups."""

from __future__ import annotations

from typing import Callable

import redis

from talim.bus.events import deserialize_event

EventHandler = Callable[[dict[str, str]], None]


class EventSubscriber:
    """Subscribes to events from Redis Streams using consumer groups."""

    def __init__(self, client: redis.Redis):
        self._client = client

    def ensure_group(self, stream_name: str, group_name: str) -> None:
        """Create a consumer group if it doesn't exist."""
        try:
            self._client.xgroup_create(stream_name, group_name, id="0", mkstream=True)
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    def read_events(
        self,
        stream_name: str,
        group_name: str,
        consumer_name: str,
        count: int = 10,
        block_ms: int = 0,
    ) -> list[tuple[str, dict[str, str]]]:
        """Read pending events from a stream consumer group.

        Args:
            stream_name: The stream key.
            group_name: Consumer group name.
            consumer_name: This consumer's name within the group.
            count: Max events to read per call.
            block_ms: Block for this many ms waiting for new events (0 = no block).

        Returns:
            List of (entry_id, event_data) tuples.
        """
        results = self._client.xreadgroup(
            group_name,
            consumer_name,
            {stream_name: ">"},
            count=count,
            block=block_ms if block_ms > 0 else None,
        )

        if not results:
            return []

        events = []
        for _stream, entries in results:
            for entry_id, data in entries:
                events.append((entry_id, data))
        return events

    def ack(self, stream_name: str, group_name: str, *entry_ids: str) -> int:
        """Acknowledge processed events."""
        return self._client.xack(stream_name, group_name, *entry_ids)

    def subscribe(
        self,
        stream_name: str,
        handler: EventHandler,
        group_name: str = "talim",
        consumer_name: str = "worker-1",
        count: int = 10,
        block_ms: int = 0,
    ) -> int:
        """Read and process events, calling handler for each.

        Returns the number of events processed.
        """
        self.ensure_group(stream_name, group_name)
        events = self.read_events(stream_name, group_name, consumer_name, count, block_ms)

        for entry_id, data in events:
            handler(data)
            self.ack(stream_name, group_name, entry_id)

        return len(events)
