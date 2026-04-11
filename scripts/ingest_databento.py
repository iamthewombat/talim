"""Ingest historical OHLCV bars from Databento (WP-28).

CLI:
    python scripts/ingest_databento.py --symbol ES --start 2024-01-01 \\
        --end 2024-01-31 --out ./data

The actual HTTP call is wrapped in `_default_fetch_day` so tests can swap in
a fake fetcher via `ingest_range(..., fetch_day=...)`.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date
from pathlib import Path

import pandas as pd

# Allow `python scripts/ingest_databento.py` to import from the sibling file.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _ingest_common import IngestResult, ingest_range  # noqa: E402


def _default_fetch_day(symbol: str, day: date) -> pd.DataFrame:  # pragma: no cover
    """Fetch one day of bars from the Databento HTTP API.

    Requires DATABENTO_API_KEY in the environment. The PoC implementation
    is intentionally a thin wrapper — production should use the official
    `databento` SDK with retry/backoff.
    """
    try:
        import databento as db  # type: ignore
    except ImportError as e:
        raise ImportError(
            "ingest_databento requires the `databento` package. "
            "Install with: pip install databento"
        ) from e

    api_key = os.environ.get("DATABENTO_API_KEY")
    if not api_key:
        raise RuntimeError("DATABENTO_API_KEY env var is required")

    client = db.Historical(key=api_key)
    next_day = day.replace(day=day.day) + pd.Timedelta(days=1).to_pytimedelta()
    data = client.timeseries.get_range(
        dataset="GLBX.MDP3",
        symbols=[symbol],
        schema="ohlcv-1m",
        start=day.isoformat(),
        end=next_day.isoformat(),
    )
    df = data.to_df().reset_index()
    df = df.rename(columns={"ts_event": "timestamp"})
    return df[["timestamp", "open", "high", "low", "close", "volume"]]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Databento OHLCV ingest (WP-28)")
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
        f"databento: wrote {len(result.written)}, "
        f"skipped {len(result.skipped)}, failed {len(result.failed)}"
    )
    return 0 if not result.failed else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
