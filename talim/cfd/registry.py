"""Registry loader for canonical CFD instrument metadata."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from talim.cfd.models import CfdInstrumentSpec, VenueCapabilities, VenueInstrumentMapping

DEFAULT_REGISTRY_ENV = "TALIM_CFD_REGISTRY_PATH"
DEFAULT_REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config" / "cfd_instruments.json"


class CfdRegistryError(ValueError):
    """Raised when the CFD registry is missing or malformed."""


@dataclass(slots=True)
class CfdInstrumentRegistry:
    """Canonical CFD instrument specs and venue capabilities."""

    instruments: dict[str, CfdInstrumentSpec]
    capabilities: dict[str, VenueCapabilities]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CfdInstrumentRegistry":
        try:
            instruments = {
                item["canonical_id"]: CfdInstrumentSpec.from_dict(item)
                for item in data.get("instruments", [])
            }
        except KeyError as exc:
            raise CfdRegistryError(f"instrument entry missing field {exc.args[0]!r}") from exc

        capabilities = {
            venue: VenueCapabilities.from_dict(venue, details)
            for venue, details in data.get("venues", {}).items()
        }
        return cls(instruments=instruments, capabilities=capabilities)

    @classmethod
    def load(cls, path: str | Path) -> "CfdInstrumentRegistry":
        registry_path = Path(path)
        try:
            raw = json.loads(registry_path.read_text())
        except FileNotFoundError as exc:
            raise CfdRegistryError(f"registry file not found: {registry_path}") from exc
        except json.JSONDecodeError as exc:
            raise CfdRegistryError(
                f"registry file is not valid JSON: {registry_path}: {exc.msg}"
            ) from exc
        return cls.from_dict(raw)

    def list_instruments(self) -> list[CfdInstrumentSpec]:
        return sorted(self.instruments.values(), key=lambda spec: spec.canonical_id)

    def get(self, canonical_id: str) -> CfdInstrumentSpec:
        try:
            return self.instruments[canonical_id]
        except KeyError as exc:
            raise CfdRegistryError(f"unknown canonical instrument {canonical_id!r}") from exc

    def resolve_mapping(self, canonical_id: str, venue: str) -> VenueInstrumentMapping:
        try:
            return self.get(canonical_id).venue_mapping(venue)
        except KeyError as exc:
            raise CfdRegistryError(str(exc)) from exc

    def get_capabilities(self, venue: str) -> VenueCapabilities:
        try:
            return self.capabilities[venue]
        except KeyError as exc:
            raise CfdRegistryError(f"unknown venue {venue!r}") from exc

    def validate_order_support(
        self,
        venue: str,
        *,
        order_type: str,
        attached_stop: bool = False,
        attached_limit: bool = False,
        guaranteed_stop: bool = False,
        working_order: bool = False,
    ) -> None:
        self.get_capabilities(venue).validate_order(
            order_type=order_type,
            attached_stop=attached_stop,
            attached_limit=attached_limit,
            guaranteed_stop=guaranteed_stop,
            working_order=working_order,
        )


def load_default_registry(path: str | Path | None = None) -> CfdInstrumentRegistry:
    configured = path or os.environ.get(DEFAULT_REGISTRY_ENV) or DEFAULT_REGISTRY_PATH
    return CfdInstrumentRegistry.load(configured)
