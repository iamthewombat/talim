"""Ingest historical OHLCV bars from Tardis.dev (WP-28).

CLI:
    python scripts/ingest_tardis.py --symbol BTCUSDT --start 2024-01-01 \\
        --end 2024-01-31 --out ./data --venue binance-futures
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _ingest_common import IngestResult, ingest_range  # noqa: E402


def _default_fetch_day(symbol: str, day: date) -> pd.DataFrame:  # pragma: no cover
    """Fetch one day of bars from Tardis.dev's HTTP API.

    Requires TARDIS_API_KEY in the environment. PoC implementation; the
    production version should use the official `tardis-dev` python client.
    """
    api_key = os.environ.get("TARDIS_API_KEY")
    if not api_key:
        raise RuntimeError("TARDIS_API_KEY env var is required")

    venue = os.environ.get("TARDIS_VENUE", "binance-futures")
    import requests

    url = (
        f"https://api.tardis.dev/v1/data-feeds/{venue}/{day.isoformat()}/"
        f"trade_bar_1m/{symbol}.csv.gz"
    )
    headers = {"Authorization": f"Bearer {api_key}"}
    resp = requests.get(url, headers=headers, timeout=120)
    resp.raise_for_status()
    df = pd.read_csv(resp.url, compression="gzip")
    df = df.rename(columns={"time": "timestamp"})
    return df[["timestamp", "open", "high", "low", "close", "volume"]]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Tardis.dev OHLCV ingest (WP-28)")
    p.add_argument("--symbol", required=True)
    p.add_argument("--start", required=True, type=date.fromisoformat)
    p.add_argument("--end", required=True, type=date.fromisoformat)
    p.add_argument("--out", required=True, type=Path)
    args = p.parse_args(argv)

    result: IngestResult = ingest_range(
        symbol=args.symbol,
        start=args.start,
        end=args.end,
        out_dir=args.out,
        fetch_day=_default_fetch_day,
    )
    print(
        f"tardis: wrote {len(result.written)}, "
        f"skipped {len(result.skipped)}, failed {len(result.failed)}"
    )
    return 0 if not result.failed else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
