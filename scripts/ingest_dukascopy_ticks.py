#!/usr/bin/env python3
"""Download Dukascopy BI5 tick data, aggregate to OHLCV, and write Talim Parquet.

Dukascopy stores one compressed BI5 file per symbol/hour at URLs like:
https://datafeed.dukascopy.com/datafeed/USA500IDXUSD/2015/00/02/14h_ticks.bi5

Months in the URL are zero-based. Tick records are 20 bytes:
- milliseconds from hour start (uint32)
- ask price integer (uint32)
- bid price integer (uint32)
- ask volume (float32)
- bid volume (float32)
"""

from __future__ import annotations

import argparse
import json
import lzma
import struct
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import pandas as pd

DUKASCOPY_BASE_URL = "https://datafeed.dukascopy.com/datafeed"
RECORD = struct.Struct(">IIIff")
# Resume-state flush cadence: at worst this many hours are re-fetched after a
# hard crash (the finally-flush covers normal exits and exceptions).
STATE_FLUSH_EVERY_HOURS = 100
TIMEFRAME_MAP = {
    "1m": "1min",
    "5m": "5min",
    "10m": "10min",
    "15m": "15min",
    "30m": "30min",
    "1h": "1h",
    "1d": "1D",
}
DEFAULT_SYMBOL_MAP = {
    "USA500IDXUSD": "US500.proxy",
    "AUSIDXAUD": "AU200.proxy",
}


@dataclass(frozen=True)
class DownloadStats:
    attempted_hours: int = 0
    downloaded_hours: int = 0
    missing_hours: int = 0
    empty_hours: int = 0
    decode_errors: int = 0
    ticks: int = 0

    def add(self, **changes: int) -> "DownloadStats":
        values = self.__dict__.copy()
        for key, value in changes.items():
            values[key] += value
        return DownloadStats(**values)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", required=True, help="Dukascopy symbol, e.g. USA500IDXUSD or AUSIDXAUD")
    parser.add_argument(
        "--instrument",
        help="Talim instrument/proxy id. Defaults to known mappings or <symbol>.proxy",
    )
    parser.add_argument("--start", required=True, help="UTC start date/time, e.g. 2015-01-05 or 2015-01-05T00:00:00Z")
    parser.add_argument("--end", required=True, help="UTC end date/time, exclusive")
    parser.add_argument("--timeframe", default="5m", choices=sorted(TIMEFRAME_MAP), help="Output bar timeframe")
    parser.add_argument(
        "--price-scale",
        default="auto",
        help="Integer price divisor. Use 'auto' for 1000 on Dukascopy index symbols, 100000 otherwise.",
    )
    parser.add_argument("--price-type", default="MID", choices=["MID", "ASK", "BID"], help="Bar price basis")
    parser.add_argument("--source", default="dukascopy", help="Source label to write into Parquet")
    parser.add_argument("--sleep-seconds", type=float, default=0.05, help="Delay between hourly requests")
    parser.add_argument("--timeout-seconds", type=float, default=15.0, help="HTTP timeout per hourly file")
    parser.add_argument(
        "--output",
        help="Output parquet path. Defaults to data/backtest/dukascopy/<instrument>/<timeframe>.parquet",
    )
    write_mode = parser.add_mutually_exclusive_group()
    write_mode.add_argument("--append", action="store_true", help="Append and deduplicate existing output")
    write_mode.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace an existing output parquet. Required for destructive rewrites.",
    )
    parser.add_argument("--manifest", help="Manifest JSON path. Defaults beside output as dataset-manifest.json")
    parser.add_argument(
        "--resume-state",
        help="JSON state path for resumable downloads. Defaults beside output as dukascopy-download-state.json",
    )
    parser.add_argument(
        "--no-resume",
        action="store_true",
        help="Do not skip hours marked completed in the resume state.",
    )
    return parser


def _parse_utc(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    if "T" not in text and len(text) == 10:
        text += "T00:00:00+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _floor_hour(dt: datetime) -> datetime:
    return dt.replace(minute=0, second=0, microsecond=0)


def _hour_cursor(start: datetime, end: datetime):
    cursor = _floor_hour(start)
    while cursor < end:
        yield cursor
        cursor += timedelta(hours=1)


def _dukascopy_url(symbol: str, hour: datetime) -> str:
    return (
        f"{DUKASCOPY_BASE_URL}/{symbol}/"
        f"{hour.year:04d}/{hour.month - 1:02d}/{hour.day:02d}/{hour.hour:02d}h_ticks.bi5"
    )


def _price_scale(symbol: str, value: str) -> int:
    if value != "auto":
        scale = int(value)
        if scale <= 0:
            raise ValueError("--price-scale must be positive")
        return scale
    # Dukascopy index CFDs are conventionally stored with 3 decimal places;
    # FX pairs use 5. This is intentionally explicit and overrideable.
    if "IDX" in symbol.upper():
        return 1000
    return 100000


def _fetch_hour(symbol: str, hour: datetime, *, timeout_seconds: float) -> bytes | None:
    # A normal GET can hang from some environments even when the file is tiny.
    # Requesting an explicit byte range makes Dukascopy return a bounded 206
    # response with Content-Length while still yielding the complete file.
    request = Request(
        _dukascopy_url(symbol, hour),
        headers={
            "User-Agent": "talim-dukascopy-ingest/1.0",
            "Accept": "*/*",
            "Connection": "close",
            "Range": "bytes=0-",
        },
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            payload = response.read()
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise
    except URLError:
        raise
    if not payload:
        return b""
    return payload


def _decode_ticks(payload: bytes, *, hour: datetime, scale: int, price_type: str) -> pd.DataFrame:
    raw = lzma.decompress(payload)
    usable = len(raw) - (len(raw) % RECORD.size)
    rows = []
    for offset in range(0, usable, RECORD.size):
        ms, ask_raw, bid_raw, ask_volume, bid_volume = RECORD.unpack_from(raw, offset)
        ask = ask_raw / scale
        bid = bid_raw / scale
        if price_type == "ASK":
            price = ask
        elif price_type == "BID":
            price = bid
        else:
            price = (ask + bid) / 2.0
        rows.append(
            {
                "timestamp": hour + timedelta(milliseconds=ms),
                "price": price,
                "volume": float(ask_volume) + float(bid_volume),
            }
        )
    return pd.DataFrame(rows)


def _aggregate_ticks(ticks: pd.DataFrame, *, timeframe: str) -> pd.DataFrame:
    if ticks.empty:
        return ticks
    frame = ticks.sort_values("timestamp").set_index("timestamp")
    rule = TIMEFRAME_MAP[timeframe]
    bars = frame.resample(rule, label="left", closed="left").agg(
        open=("price", "first"),
        high=("price", "max"),
        low=("price", "min"),
        close=("price", "last"),
        volume=("volume", "sum"),
    )
    bars = bars.dropna(subset=["open", "high", "low", "close"]).reset_index()
    return bars


def _default_output(instrument: str, timeframe: str, price_type: str) -> Path:
    safe = instrument.replace("/", "-")
    return Path("data") / "backtest" / "dukascopy" / safe / f"{timeframe}-{price_type.lower()}.parquet"


def _merge_existing(frame: pd.DataFrame, output: Path, *, append: bool, overwrite: bool, price_type: str) -> pd.DataFrame:
    if output.exists() and not append and not overwrite:
        raise ValueError(
            f"refusing to overwrite existing Dukascopy parquet {output}; "
            "use --append for incremental pulls or --overwrite for an explicit destructive rewrite"
        )
    if append and output.exists():
        existing = pd.read_parquet(output)
        if "price_type" not in existing.columns:
            raise ValueError(f"cannot append to {output}: existing file has no price_type column")
        existing_price_types = set(existing["price_type"].dropna().astype(str).unique())
        if existing_price_types - {price_type}:
            raise ValueError(
                f"refusing to append {price_type} bars to {output}: "
                f"existing price_type values are {sorted(existing_price_types)}"
            )
        frame = pd.concat([existing, frame], ignore_index=True)
    if frame.empty:
        return frame
    return frame.drop_duplicates(subset=["timestamp", "price_type"], keep="last").sort_values("timestamp").reset_index(drop=True)


def _write_manifest(path: Path, *, args: argparse.Namespace, instrument: str, start: datetime, end: datetime, output: Path, stats: DownloadStats, rows: int, scale: int) -> None:
    manifest = {
        "source": args.source,
        "vendor": "Dukascopy Bank SA",
        "symbol": args.symbol,
        "instrument": instrument,
        "timeframe": args.timeframe,
        "price_type": args.price_type,
        "price_scale": scale,
        "requested_start_utc": start.isoformat(),
        "requested_end_utc_exclusive": end.isoformat(),
        "output": str(output),
        "rows": rows,
        "stats": stats.__dict__,
        "notes": [
            "Dukascopy months are zero-based in raw datafeed URLs.",
            "Dataset is a proxy source and should not be merged into venue-specific FOREX.com files.",
            "Raw BI5 ticks were aggregated locally; verify source terms before non-internal use.",
        ],
        "generated_at_utc": datetime.now(UTC).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def _load_state(path: Path, *, args: argparse.Namespace, instrument: str) -> dict:
    if path.exists():
        try:
            state = json.loads(path.read_text())
        except json.JSONDecodeError:
            state = {}
    else:
        state = {}
    state.setdefault("source", args.source)
    state.setdefault("symbol", args.symbol)
    state.setdefault("instrument", instrument)
    state.setdefault("completed_hours", [])
    state.setdefault("missing_hours", [])
    state.setdefault("empty_hours", [])
    state.setdefault("decode_error_hours", [])
    state.setdefault("fetch_error_hours", {})
    return state


def _write_state(path: Path, state: dict) -> None:
    state["updated_at_utc"] = datetime.now(UTC).isoformat()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def _state_key(hour: datetime) -> str:
    return hour.isoformat().replace("+00:00", "Z")


def _append_unique(state: dict, field: str, value: str) -> None:
    values = set(state.setdefault(field, []))
    values.add(value)
    state[field] = sorted(values)


def main() -> int:
    args = _build_parser().parse_args()
    start = _parse_utc(args.start)
    end = _parse_utc(args.end)
    if start >= end:
        raise ValueError("--start must be before --end")

    if args.append:
        # Appended bars are rebuilt from only the requested window, and the
        # merge dedupe keeps the newest row per (timestamp, price_type) — so a
        # partial re-pull of a coarse bar REPLACES the previously complete bar.
        if args.timeframe == "1d":
            print(
                "WARNING: --append with --timeframe 1d: re-pulling a partial day "
                "replaces the existing full-day bar with one built from only the "
                "re-pulled hours. Re-pull whole days, or aggregate daily bars "
                "from a finer-timeframe parquet instead."
            )
        if start != _floor_hour(start) or end != _floor_hour(end):
            print(
                "WARNING: --append with a start/end not aligned to the hour can "
                "rebuild partial bars that replace complete ones."
            )

    instrument = args.instrument or DEFAULT_SYMBOL_MAP.get(args.symbol.upper(), f"{args.symbol}.proxy")
    output = Path(args.output) if args.output else _default_output(instrument, args.timeframe, args.price_type)
    manifest = Path(args.manifest) if args.manifest else output.with_name(f"{output.stem}-manifest.json")
    state_path = Path(args.resume_state) if args.resume_state else output.with_name(f"{output.stem}-download-state.json")
    output.parent.mkdir(parents=True, exist_ok=True)
    scale = _price_scale(args.symbol, args.price_scale)
    state = _load_state(state_path, args=args, instrument=instrument)
    completed_before = set(state.get("completed_hours", []))

    tick_frames: list[pd.DataFrame] = []
    stats = DownloadStats()
    # Rewriting the whole (growing) state JSON after every hour is O(n^2) over
    # a multi-year pull, so flush every N dirty hours and always on exit.
    pending_state_writes = 0

    def _flush_state(*, force: bool = False) -> None:
        nonlocal pending_state_writes
        if pending_state_writes == 0:
            return
        if not force and pending_state_writes < STATE_FLUSH_EVERY_HOURS:
            return
        _write_state(state_path, state)
        pending_state_writes = 0

    try:
        for hour in _hour_cursor(start, end):
            hour_key = _state_key(hour)
            if not args.no_resume and hour_key in completed_before:
                continue
            stats = stats.add(attempted_hours=1)
            try:
                payload = _fetch_hour(args.symbol, hour, timeout_seconds=args.timeout_seconds)
            except Exception as exc:  # network/provider errors should not corrupt partial imports
                print(f"{hour.isoformat()} fetch error: {exc}")
                state.setdefault("fetch_error_hours", {})[hour_key] = str(exc)
                pending_state_writes += 1
                _flush_state()
                stats = stats.add(missing_hours=1)
                continue
            if payload is None:
                _append_unique(state, "missing_hours", hour_key)
                pending_state_writes += 1
                _flush_state()
                stats = stats.add(missing_hours=1)
                continue
            if payload == b"":
                _append_unique(state, "empty_hours", hour_key)
                pending_state_writes += 1
                _flush_state()
                stats = stats.add(empty_hours=1)
                continue
            try:
                ticks = _decode_ticks(payload, hour=hour, scale=scale, price_type=args.price_type)
            except Exception as exc:
                print(f"{hour.isoformat()} decode error: {exc}")
                _append_unique(state, "decode_error_hours", hour_key)
                pending_state_writes += 1
                _flush_state()
                stats = stats.add(decode_errors=1)
                continue
            if ticks.empty:
                _append_unique(state, "empty_hours", hour_key)
                pending_state_writes += 1
                _flush_state()
                stats = stats.add(empty_hours=1)
                continue
            tick_frames.append(ticks)
            _append_unique(state, "completed_hours", hour_key)
            pending_state_writes += 1
            _flush_state()
            stats = stats.add(downloaded_hours=1, ticks=len(ticks))
            if args.sleep_seconds > 0:
                time.sleep(args.sleep_seconds)
    finally:
        _flush_state(force=True)

    ticks = pd.concat(tick_frames, ignore_index=True) if tick_frames else pd.DataFrame(columns=["timestamp", "price", "volume"])
    if not ticks.empty:
        ticks = ticks[(ticks["timestamp"] >= start) & (ticks["timestamp"] < end)]
    bars = _aggregate_ticks(ticks, timeframe=args.timeframe)
    if not bars.empty:
        fetched_at = datetime.now(UTC).isoformat()
        bars.insert(0, "instrument", instrument)
        bars["timeframe"] = args.timeframe
        bars["price_type"] = args.price_type
        bars["source"] = args.source
        bars["fetched_at_utc"] = fetched_at
    else:
        bars = pd.DataFrame(
            columns=[
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
        )
    bars = _merge_existing(bars, output, append=args.append, overwrite=args.overwrite, price_type=args.price_type)
    bars.to_parquet(output, index=False)
    _write_manifest(manifest, args=args, instrument=instrument, start=start, end=end, output=output, stats=stats, rows=len(bars), scale=scale)

    if bars.empty:
        print(f"wrote 0 bars to {output}; stats={stats}")
    else:
        print(
            f"wrote {len(bars)} bars to {output} "
            f"({bars['timestamp'].min()} .. {bars['timestamp'].max()}); stats={stats}"
        )
    print(f"wrote manifest to {manifest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
