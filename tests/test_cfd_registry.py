"""Tests for the canonical CFD contract registry."""

from __future__ import annotations

import pytest

from talim.cfd import CfdInstrumentRegistry, load_default_registry


class TestDefaultRegistry:
    def test_loads_au200_cash(self):
        registry = load_default_registry()
        spec = registry.get("AU200.cash")
        mapping = registry.resolve_mapping("AU200.cash", "ig")

        assert spec.display_name == "Australia 200 Cash CFD"
        assert spec.quote_currency == "AUD"
        assert spec.margin_rate == 0.05
        assert mapping.lookup_hint == "Australia 200"
        assert mapping.is_resolved is True
        assert mapping.broker_symbol == "IX.D.ASX.IFT.IP"

    def test_session_metadata_loads_cleanly(self):
        registry = load_default_registry()
        spec = registry.get("AU200.fwd")

        assert spec.session.timezone == "Australia/Sydney"
        assert len(spec.session.windows) == 1
        window = spec.session.windows[0]
        assert window.opens_day == "MON"
        assert window.opens_time == "08:00"
        assert window.closes_day == "SAT"
        assert window.closes_time == "07:00"

    def test_trade_readiness_requires_resolved_fields(self):
        registry = load_default_registry()
        spec = registry.get("AU200.cash")

        assert spec.is_trade_ready("ig") is False
        missing = set(spec.missing_trade_fields())
        assert {"tick_size", "price_precision", "min_size", "size_step"} <= missing
        assert spec.point_value == 1.0


class TestVenueCapabilities:
    def test_rejects_unsupported_order_combinations(self):
        registry = CfdInstrumentRegistry.from_dict({
            "venues": {
                "paper": {
                    "supports_market_orders": True,
                    "supports_marketable_limits": False,
                    "supports_limit_orders": True,
                    "supports_stop_orders": False,
                    "supports_attached_stops_limits": False,
                    "supports_guaranteed_stops": False,
                    "supports_partial_fills": True,
                    "supports_working_orders": False,
                    "supports_streaming_prices": True,
                    "supports_demo": True,
                    "supports_live": False,
                    "position_model": "netted",
                }
            },
            "instruments": [
                {
                    "canonical_id": "TEST.cash",
                    "display_name": "Test Cash CFD",
                    "asset_class": "index_cfd",
                    "quote_currency": "USD",
                    "session": {
                        "timezone": "UTC",
                        "windows": [
                            {
                                "opens_day": "MON",
                                "opens_time": "00:00",
                                "closes_day": "FRI",
                                "closes_time": "23:59",
                            }
                        ],
                    },
                    "venues": {
                        "paper": {
                            "lookup_hint": "Test Cash CFD",
                        }
                    },
                }
            ],
        })

        with pytest.raises(ValueError, match="guaranteed stops"):
            registry.validate_order_support("paper", order_type="market", guaranteed_stop=True)

        with pytest.raises(ValueError, match="attached stop/limit"):
            registry.validate_order_support("paper", order_type="market", attached_stop=True)

        with pytest.raises(ValueError, match="working orders"):
            registry.validate_order_support("paper", order_type="market", working_order=True)
