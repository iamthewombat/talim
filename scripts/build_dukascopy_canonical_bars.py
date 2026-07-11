#!/usr/bin/env python3
"""Build canonical combined Dukascopy OHLCV parquet files.

The historical Dukascopy backfill stores full-history AU200 data as split files:

    data/backtest/dukascopy/AU200.proxy/5m-mid.parquet
    data/backtest/dukascopy/AU200.proxy/5m-bid.parquet
    data/backtest/dukascopy/AU200.proxy/5m-ask.parquet

Feature builders expect combined venue-style files at:

    data/<venue>/<instrument>/<timeframe>.parquet

This script creates that canonical layout without modifying the original split
backtest files, then derives higher timeframes from the 5m bars per price type.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

TIMEFRAME_RULES = {
    "30m": "30min",
    "1h": "1h",
    "1d": "1D",
}
CANONICAL_COLUMNS = [
    "instrument",
    "timestamp",
    "open",
    "high",
    "low",
    "close",
    "volume",
    "timeframe",
    "price_type",
    "source",
    "fetched_at_utc",
]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instrument", default="AU200.proxy")
    parser.add_argument("--source-root", default="data/backtest/dukascopy")
    parser.add_argument("--output-root", default="data/dukascopy")
    parser.add_argument("--base-timeframe", default="5m", choices=["5m"])
    parser.add_argument(
        "--derive-timeframe",
        action="append",
        default=[],
        choices=sorted(TIMEFRAME_RULES),
        help="Higher timeframe to derive; may be repeated. Defaults to all.",
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser


def _load_split(source_dir: Path, timeframe: str, price_type: str) -> pd.DataFrame:
    path = source_dir / f"{timeframe}-{price_type.lower()}.parquet"
    if not path.exists():
        raise FileNotFoundError(path)
    frame = pd.read_parquet(path)
    missing = set(CANONICAL_COLUMNS) - set(frame.columns)
    if missing:
        raise ValueError(f"{path} missing columns: {sorted(missing)}")
    frame = frame[CANONICAL_COLUMNS].copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame["price_type"] = frame["price_type"].astype(str).str.upper()
    expected = price_type.upper()
    actual = set(frame["price_type"].dropna().unique())
    if actual != {expected}:
        raise ValueError(f"{path} expected only {expected}, found {sorted(actual)}")
    return frame


def _normalise(frame: pd.DataFrame, *, instrument: str, timeframe: str) -> pd.DataFrame:
    frame = frame.copy()
    frame["instrument"] = instrument
    frame["timeframe"] = timeframe
    frame["source"] = "dukascopy"
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True)
    frame = frame.drop_duplicates(subset=["timestamp", "price_type"], keep="last")
    frame = frame.sort_values(["timestamp", "price_type"]).reset_index(drop=True)
    return frame[CANONICAL_COLUMNS]


def _timestamp_to_iso(frame: pd.DataFrame) -> pd.DataFrame:
    frame = frame.copy()
    frame["timestamp"] = pd.to_datetime(frame["timestamp"], utc=True).dt.strftime("%Y-%m-%dT%H:%M:%S%z")
    frame["timestamp"] = frame["timestamp"].str.replace(r"\+0000$", "+00:00", regex=True)
    return frame


def _write_parquet(frame: pd.DataFrame, path: Path, *, overwrite: bool) -> None:
    if path.exists() and not overwrite:
        raise FileExistsError(f"refusing to overwrite {path}; pass --overwrite")
    path.parent.mkdir(parents=True, exist_ok=True)
    _timestamp_to_iso(frame).to_parquet(path, index=False)


def _derive(frame_5m: pd.DataFrame, *, instrument: str, timeframe: str) -> pd.DataFrame:
    rule = TIMEFRAME_RULES[timeframe]
    pieces: list[pd.DataFrame] = []
    for price_type, group in frame_5m.groupby("price_type", sort=True):
        group = group.sort_values("timestamp").set_index("timestamp")
        bars = group.resample(rule, label="left", closed="left").agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
            fetched_at_utc=("fetched_at_utc", "max"),
        )
        bars = bars.dropna(subset=["open", "high", "low", "close"]).reset_index()
        bars["instrument"] = instrument
        bars["timeframe"] = timeframe
        bars["price_type"] = price_type
        bars["source"] = "dukascopy"
        pieces.append(bars[CANONICAL_COLUMNS])
    if not pieces:
        return pd.DataFrame(columns=CANONICAL_COLUMNS)
    return _normalise(pd.concat(pieces, ignore_index=True), instrument=instrument, timeframe=timeframe)


def _summary(frame: pd.DataFrame, path: Path) -> dict[str, object]:
    counts = frame["price_type"].value_counts().sort_index().to_dict() if not frame.empty else {}
    return {
        "path": str(path),
        "rows": int(len(frame)),
        "price_type_counts": {str(k): int(v) for k, v in counts.items()},
        "first_timestamp": str(frame["timestamp"].min()) if not frame.empty else None,
        "last_timestamp": str(frame["timestamp"].max()) if not frame.empty else None,
        "duplicate_timestamp_price_type_rows": int(frame.duplicated(["timestamp", "price_type"]).sum()) if not frame.empty else 0,
    }


def main() -> int:
    args = _build_parser().parse_args()
    source_dir = Path(args.source_root) / args.instrument
    output_dir = Path(args.output_root) / args.instrument
    derive_timeframes = args.derive_timeframe or sorted(TIMEFRAME_RULES)

    split = [_load_split(source_dir, args.base_timeframe, pt) for pt in ("MID", "BID", "ASK")]
    base = _normalise(pd.concat(split, ignore_index=True), instrument=args.instrument, timeframe=args.base_timeframe)

    summaries: list[dict[str, object]] = []
    base_path = output_dir / f"{args.base_timeframe}.parquet"
    _write_parquet(base, base_path, overwrite=args.overwrite)
    summaries.append(_summary(base, base_path))

    for timeframe in derive_timeframes:
        derived = _derive(base, instrument=args.instrument, timeframe=timeframe)
        path = output_dir / f"{timeframe}.parquet"
        _write_parquet(derived, path, overwrite=args.overwrite)
        summaries.append(_summary(derived, path))

    manifest = {
        "instrument": args.instrument,
        "source_root": str(source_dir),
        "output_root": str(output_dir),
        "base_timeframe": args.base_timeframe,
        "derived_timeframes": derive_timeframes,
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "summaries": summaries,
    }
    manifest_path = output_dir / "canonical-bars-manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    for item in summaries:
        print(
            f"{Path(str(item['path'])).name}: wrote {item['rows']} rows "
            f"{item['price_type_counts']} [{item['first_timestamp']} .. {item['last_timestamp']}]"
        )
    print(f"manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
