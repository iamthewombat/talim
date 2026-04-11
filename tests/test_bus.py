"""Tests for the Redis event bus using fakeredis."""

import fakeredis

from talim.bus.events import (
    BarEvent,
    RegimeChangeEvent,
    SignalEvent,
    TradeEvent,
    deserialize_event,
)
from talim.bus.publisher import EventPublisher
from talim.bus.subscriber import EventSubscriber


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fakeredis() -> fakeredis.FakeRedis:
    return fakeredis.FakeRedis(decode_responses=True)


def _make_bar_event() -> BarEvent:
    return BarEvent(
        instrument="ES",
        timestamp="2025-06-15T09:30:00",
        open=5400.0,
        high=5410.0,
        low=5395.0,
        close=5405.0,
        volume=12000.0,
        timeframe="5m",
    )


# ---------------------------------------------------------------------------
# Event serialisation tests
# ---------------------------------------------------------------------------

class TestEventSerialisation:
    def test_bar_event_roundtrip(self):
        event = _make_bar_event()
        d = event.to_dict()
        restored = BarEvent.from_dict(d)
        assert restored.instrument == event.instrument
        assert restored.close == event.close

    def test_regime_change_roundtrip(self):
        event = RegimeChangeEvent(
            instrument="ES",
            old_regime="momentum",
            new_regime="high_vol",
            timestamp="2025-06-15T12:00:00",
        )
        d = event.to_dict()
        restored = RegimeChangeEvent.from_dict(d)
        assert restored.old_regime == "momentum"
        assert restored.new_regime == "high_vol"

    def test_signal_event_roundtrip(self):
        event = SignalEvent(
            instrument="ES",
            strategy="momentum-ES",
            side="long",
            entry_price=5400.0,
            stop=5380.0,
            target=5440.0,
            rationale="EMA crossover",
            timestamp="2025-06-15T09:35:00",
        )
        d = event.to_dict()
        restored = SignalEvent.from_dict(d)
        assert restored.strategy == "momentum-ES"
        assert restored.entry_price == 5400.0

    def test_trade_event_roundtrip(self):
        event = TradeEvent(
            instrument="ES",
            strategy="momentum-ES",
            side="long",
            qty=2.0,
            fill_price=5401.0,
            timestamp="2025-06-15T09:36:00",
        )
        d = event.to_dict()
        restored = TradeEvent.from_dict(d)
        assert restored.qty == 2.0
        assert restored.fill_price == 5401.0

    def test_deserialize_event_dispatch(self):
        for event in [_make_bar_event(), RegimeChangeEvent(), SignalEvent(), TradeEvent()]:
            d = event.to_dict()
            restored = deserialize_event(d)
            assert type(restored) == type(event)


# ---------------------------------------------------------------------------
# Publisher + Subscriber integration tests (fakeredis)
# ---------------------------------------------------------------------------

class TestPublishSubscribe:
    def test_publish_and_receive_one(self):
        client = _make_fakeredis()
        pub = EventPublisher(client)
        sub = EventSubscriber(client)

        event = _make_bar_event()
        entry_id = pub.publish("talim:bars", event)
        assert entry_id is not None

        received: list[dict] = []
        sub.subscribe(
            "talim:bars",
            handler=lambda data: received.append(data),
            group_name="test-group",
            consumer_name="test-consumer",
        )

        assert len(received) == 1
        assert received[0]["instrument"] == "ES"
        assert received[0]["close"] == "5405.0"

    def test_publish_100_receive_all(self):
        client = _make_fakeredis()
        pub = EventPublisher(client)
        sub = EventSubscriber(client)

        for i in range(100):
            event = BarEvent(
                instrument="ES",
                timestamp=f"2025-06-15T09:{i // 60:02d}:{i % 60:02d}",
                close=5000.0 + i,
            )
            pub.publish("talim:bars", event)

        received: list[dict] = []
        # Read in batches
        total = 0
        sub.ensure_group("talim:bars", "test-group")
        while True:
            events = sub.read_events(
                "talim:bars", "test-group", "worker-1", count=50
            )
            if not events:
                break
            for entry_id, data in events:
                received.append(data)
                sub.ack("talim:bars", "test-group", entry_id)
            total += len(events)

        assert len(received) == 100

    def test_events_in_order(self):
        client = _make_fakeredis()
        pub = EventPublisher(client)
        sub = EventSubscriber(client)

        for i in range(20):
            event = BarEvent(instrument="ES", close=float(i))
            pub.publish("talim:bars", event)

        received: list[dict] = []
        sub.subscribe(
            "talim:bars",
            handler=lambda data: received.append(data),
            group_name="order-test",
            consumer_name="worker-1",
            count=20,
        )

        closes = [float(r["close"]) for r in received]
        assert closes == list(range(20))

    def test_multiple_streams(self):
        client = _make_fakeredis()
        pub = EventPublisher(client)
        sub = EventSubscriber(client)

        pub.publish("talim:bars", _make_bar_event())
        pub.publish("talim:signals", SignalEvent(instrument="NQ", strategy="test"))

        bars: list[dict] = []
        signals: list[dict] = []

        sub.subscribe("talim:bars", handler=bars.append, group_name="g1", consumer_name="w1")
        sub.subscribe("talim:signals", handler=signals.append, group_name="g1", consumer_name="w1")

        assert len(bars) == 1
        assert bars[0]["instrument"] == "ES"
        assert len(signals) == 1
        assert signals[0]["instrument"] == "NQ"

    def test_ack_prevents_redelivery(self):
        client = _make_fakeredis()
        pub = EventPublisher(client)
        sub = EventSubscriber(client)

        pub.publish("talim:bars", _make_bar_event())

        received: list[dict] = []
        sub.subscribe("talim:bars", handler=received.append, group_name="g1", consumer_name="w1")
        assert len(received) == 1

        # Second read should get nothing (already acked)
        received2: list[dict] = []
        count = sub.subscribe("talim:bars", handler=received2.append, group_name="g1", consumer_name="w1")
        assert count == 0
