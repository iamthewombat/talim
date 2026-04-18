#!/usr/bin/env python3
"""Discover IG CFD markets and print registry-ready mapping data."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from typing import Any

from talim.cfd import load_default_registry
from talim.connectors.exchange.ig_discovery import IgCredentials, IgDiscoveryClient


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--canonical-id",
        help="Canonical CFD instrument id to resolve from the registry, e.g. AU200.cash",
    )
    parser.add_argument(
        "--query",
        help="IG market search term. If omitted, the registry lookup hint is used.",
    )
    parser.add_argument(
        "--epic",
        help="Fetch a specific IG market epic directly instead of choosing from search results.",
    )
    parser.add_argument(
        "--registry-path",
        help="Optional registry JSON path. Defaults to TALIM_CFD_REGISTRY_PATH or config/cfd_instruments.json",
    )
    parser.add_argument(
        "--select",
        type=int,
        default=0,
        help="When searching, fetch details for this result index (default: 0)",
    )
    parser.add_argument(
        "--search-only",
        action="store_true",
        help="Only print search results; do not fetch market details.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print machine-readable JSON only.",
    )
    return parser


def _dump(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(json.dumps(payload, indent=2))


def main() -> int:
    args = _build_parser().parse_args()
    registry = load_default_registry(args.registry_path)

    query = args.query
    if args.canonical_id and not query and not args.epic:
        query = registry.resolve_mapping(args.canonical_id, "ig").lookup_hint

    if not query and not args.epic:
        raise SystemExit("Provide --query, --epic, or --canonical-id")

    credentials = IgCredentials.from_env()
    with IgDiscoveryClient(credentials) as client:
        search_results = []
        details = None

        if args.epic:
            details = client.get_market(args.epic)
        else:
            search_results = client.search_markets(query or "")
            if args.search_only:
                _dump(
                    {
                        "query": query,
                        "results": [asdict(result) for result in search_results],
                    },
                    as_json=args.json,
                )
                return 0
            if not search_results:
                raise SystemExit(f"No IG markets found for query {query!r}")
            if args.select < 0 or args.select >= len(search_results):
                raise SystemExit(
                    f"--select {args.select} is out of range for {len(search_results)} search results"
                )
            details = client.get_market(search_results[args.select].epic)

        payload: dict[str, Any] = {
            "search_results": [asdict(result) for result in search_results],
            "details": {
                "epic": details.epic,
                "instrument_name": details.instrument_name,
                "instrument_type": details.instrument_type,
                "expiry": details.expiry,
                "currency": details.currency,
                "market_status": details.market_status,
                "margin_factor": details.margin_factor,
                "margin_factor_unit": details.margin_factor_unit,
                "min_deal_size": details.min_deal_size,
                "lot_size": details.lot_size,
                "one_pip_means": details.one_pip_means,
                "opening_hours": details.opening_hours,
            },
        }
        if args.canonical_id:
            payload["registry_patch"] = client.build_registry_patch(
                canonical_id=args.canonical_id,
                details=details,
                lookup_hint=query,
            )

        _dump(payload, as_json=args.json)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
