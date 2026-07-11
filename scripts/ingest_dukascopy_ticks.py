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
import concurrent.futures
import json
import lzma
import random
import struct
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
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
_THREAD_LOCAL = threading.local()


@dataclass(frozen=True)
class DownloadStats:
    attempted_hours: int = 0
    downloaded_hours: int = 0
    missing_hours: int = 0
    empty_hours: int = 0
    decode_errors: int = 0
    ticks: int = 0
    cache_hits: int = 0
    http_downloads: int = 0
    closure_hours: int = 0
    retry_attempts: int = 0
    retry_recovered_hours: int = 0

    def add(self, **changes: int) -> "DownloadStats":
        values = self.__dict__.copy()
        for key, value in changes.items():
            values[key] += value
        return DownloadStats(**values)


@dataclass(frozen=True)
class RawHourResult:
    hour: datetime
    payload: bytes | None
    source: str
    attempts: int = 0
    recovered: bool = False
    error: str | None = None


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
    parser.add_argument("--max-fetch-retries", type=int, default=3, help="Retries for transient hourly fetch failures")
    parser.add_argument("--backoff-base-seconds", type=float, default=2.0, help="Base delay for exponential fetch backoff")
    parser.add_argument("--workers", type=int, default=1, help="Bounded hourly fetch/decode workers")
    parser.add_argument(
        "--raw-cache-dir",
        default="data/cache/dukascopy/bi5",
        help="Directory for raw .bi5 cache files",
    )
    parser.add_argument("--no-raw-cache", action="store_true", help="Disable raw .bi5 disk cache")
    parser.add_argument(
        "--include-market-closures",
        action="store_true",
        help="Fetch obvious closure hours instead of marking them as skipped",
    )
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


def _is_market_closure_hour(symbol: str, hour: datetime) -> bool:
    """Conservative closure filter for obvious dead Dukascopy index-CFD hours."""
    symbol_upper = symbol.upper()
    weekday = hour.weekday()
    if weekday == 5:
        return True
    if weekday == 6 and hour.hour < 18:
        return True
    if weekday == 4 and hour.hour >= 22:
        return True
    if "IDX" in symbol_upper and (hour.month, hour.day) in {(1, 1), (12, 25)}:
        return True
    return False


def _dukascopy_url(symbol: str, hour: datetime) -> str:
    return (
        f"{DUKASCOPY_BASE_URL}/{symbol}/"
        f"{hour.year:04d}/{hour.month - 1:02d}/{hour.day:02d}/{hour.hour:02d}h_ticks.bi5"
    )


def _raw_cache_path(cache_dir: Path, symbol: str, hour: datetime) -> Path:
    return (
        cache_dir
        / symbol.upper()
        / f"{hour.year:04d}"
        / f"{hour.month:02d}"
        / f"{hour.day:02d}"
        / f"{hour.hour:02d}h_ticks.bi5"
    )


def _read_cached_hour(cache_dir: Path | None, symbol: str, hour: datetime) -> bytes | None:
    if cache_dir is None:
        return None
    path = _raw_cache_path(cache_dir, symbol, hour)
    if not path.exists():
        return None
    return path.read_bytes()


def _write_cached_hour(cache_dir: Path | None, symbol: str, hour: datetime, payload: bytes) -> None:
    if cache_dir is None or not payload:
        return
    path = _raw_cache_path(cache_dir, symbol, hour)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp-{random.randrange(1_000_000_000):09d}")
    tmp.write_bytes(payload)
    tmp.replace(path)


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


def _fetch_hour(
    symbol: str,
    hour: datetime,
    *,
    timeout_seconds: float,
    client: httpx.Client | None = None,
) -> bytes | None:
    # A normal GET can hang from some environments even when the file is tiny.
    # Requesting an explicit byte range makes Dukascopy return a bounded 206
    # response with Content-Length while still yielding the complete file.
    headers = {
        "User-Agent": "talim-dukascopy-ingest/1.0",
        "Accept": "*/*",
        "Range": "bytes=0-",
    }
    close_client = client is None
    if client is None:
        client = httpx.Client(timeout=timeout_seconds)
    try:
        response = client.get(_dukascopy_url(symbol, hour), headers=headers, timeout=timeout_seconds)
        if response.status_code == 404:
            return None
        response.raise_for_status()
        payload = response.content
    finally:
        if close_client:
            client.close()
    if not payload:
        return b""
    return payload


def _fetch_raw_hour(
    symbol: str,
    hour: datetime,
    *,
    timeout_seconds: float,
    cache_dir: Path | None,
    max_retries: int,
    backoff_base_seconds: float,
    client: httpx.Client | None = None,
    sleep: bool = True,
) -> RawHourResult:
    cached = _read_cached_hour(cache_dir, symbol, hour)
    if cached is not None:
        return RawHourResult(hour=hour, payload=cached, source="cache")

    attempts = 0
    last_error: str | None = None
    transient_statuses = {408, 429, 500, 502, 503, 504}
    total_attempts = max(1, max_retries + 1)
    for attempt in range(1, total_attempts + 1):
        attempts = attempt
        try:
            payload = _fetch_hour(symbol, hour, timeout_seconds=timeout_seconds, client=client)
            if payload is not None:
                _write_cached_hour(cache_dir, symbol, hour, payload)
            return RawHourResult(
                hour=hour,
                payload=payload,
                source="http",
                attempts=attempts,
                recovered=attempts > 1,
            )
        except httpx.HTTPStatusError as exc:
            last_error = str(exc)
            if exc.response.status_code not in transient_statuses or attempt == total_attempts:
                break
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            last_error = str(exc)
            if attempt == total_attempts:
                break
        if sleep:
            delay = backoff_base_seconds * (2 ** (attempt - 1))
            time.sleep(delay + random.uniform(0, min(1.0, backoff_base_seconds)))
    return RawHourResult(hour=hour, payload=None, source="error", attempts=attempts, error=last_error)


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
    state.setdefault("closure_hours", [])
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


def _remove_problem_hour(state: dict, hour_key: str) -> None:
    for field in ("missing_hours", "empty_hours", "decode_error_hours", "closure_hours"):
        if hour_key in state.setdefault(field, []):
            state[field] = sorted(set(state[field]) - {hour_key})
    state.setdefault("fetch_error_hours", {}).pop(hour_key, None)


def _thread_client(timeout_seconds: float) -> httpx.Client:
    client = getattr(_THREAD_LOCAL, "dukascopy_client", None)
    if client is None:
        client = httpx.Client(timeout=timeout_seconds)
        _THREAD_LOCAL.dukascopy_client = client
    return client


def _fetch_raw_hour_for_pool(
    symbol: str,
    hour: datetime,
    timeout_seconds: float,
    cache_dir: Path | None,
    max_retries: int,
    backoff_base_seconds: float,
) -> RawHourResult:
    return _fetch_raw_hour(
        symbol,
        hour,
        timeout_seconds=timeout_seconds,
        cache_dir=cache_dir,
        max_retries=max_retries,
        backoff_base_seconds=backoff_base_seconds,
        client=_thread_client(timeout_seconds),
    )


def run_ingest(args: argparse.Namespace) -> int:
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
    cache_dir = None if args.no_raw_cache else Path(args.raw_cache_dir)

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
        hours: list[datetime] = []
        for hour in _hour_cursor(start, end):
            hour_key = _state_key(hour)
            if not args.no_resume and hour_key in completed_before:
                continue
            if not args.include_market_closures and _is_market_closure_hour(args.symbol, hour):
                _append_unique(state, "closure_hours", hour_key)
                pending_state_writes += 1
                _flush_state()
                stats = stats.add(closure_hours=1)
                continue
            hours.append(hour)

        def handle_result(result: RawHourResult) -> None:
            nonlocal stats, pending_state_writes
            hour = result.hour
            stats = stats.add(attempted_hours=1)
            hour_key = _state_key(hour)
            stats = stats.add(retry_attempts=max(0, result.attempts - 1))
            if result.recovered:
                stats = stats.add(retry_recovered_hours=1)
            if result.source == "cache":
                stats = stats.add(cache_hits=1)
            elif result.source == "http" and result.payload is not None:
                stats = stats.add(http_downloads=1)
            if result.source == "error":
                print(f"{hour.isoformat()} fetch error: {result.error}")
                state.setdefault("fetch_error_hours", {})[hour_key] = result.error or "fetch failed"
                pending_state_writes += 1
                _flush_state()
                stats = stats.add(missing_hours=1)
                return
            payload = result.payload
            if payload is None:
                _remove_problem_hour(state, hour_key)
                _append_unique(state, "missing_hours", hour_key)
                pending_state_writes += 1
                _flush_state()
                stats = stats.add(missing_hours=1)
                return
            if payload == b"":
                _remove_problem_hour(state, hour_key)
                _append_unique(state, "empty_hours", hour_key)
                pending_state_writes += 1
                _flush_state()
                stats = stats.add(empty_hours=1)
                return
            try:
                ticks = _decode_ticks(payload, hour=hour, scale=scale, price_type=args.price_type)
            except Exception as exc:
                print(f"{hour.isoformat()} decode error: {exc}")
                _remove_problem_hour(state, hour_key)
                _append_unique(state, "decode_error_hours", hour_key)
                pending_state_writes += 1
                _flush_state()
                stats = stats.add(decode_errors=1)
                return
            if ticks.empty:
                _remove_problem_hour(state, hour_key)
                _append_unique(state, "empty_hours", hour_key)
                pending_state_writes += 1
                _flush_state()
                stats = stats.add(empty_hours=1)
                return
            tick_frames.append(ticks)
            _remove_problem_hour(state, hour_key)
            _append_unique(state, "completed_hours", hour_key)
            pending_state_writes += 1
            _flush_state()
            stats = stats.add(downloaded_hours=1, ticks=len(ticks))

        workers = max(1, int(args.workers))
        if workers == 1:
            with httpx.Client(timeout=args.timeout_seconds) as client:
                for hour in hours:
                    result = _fetch_raw_hour(
                        args.symbol,
                        hour,
                        timeout_seconds=args.timeout_seconds,
                        cache_dir=cache_dir,
                        max_retries=args.max_fetch_retries,
                        backoff_base_seconds=args.backoff_base_seconds,
                        client=client,
                    )
                    handle_result(result)
                    if args.sleep_seconds > 0:
                        time.sleep(args.sleep_seconds)
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
                futures = [
                    executor.submit(
                        _fetch_raw_hour_for_pool,
                        args.symbol,
                        hour,
                        args.timeout_seconds,
                        cache_dir,
                        args.max_fetch_retries,
                        args.backoff_base_seconds,
                    )
                    for hour in hours
                ]
                for future in concurrent.futures.as_completed(futures):
                    handle_result(future.result())
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
    state["last_run_stats"] = stats.__dict__
    state["last_run_window"] = {
        "start_utc": start.isoformat(),
        "end_utc_exclusive": end.isoformat(),
        "price_type": args.price_type,
        "timeframe": args.timeframe,
        "workers": workers,
        "raw_cache_dir": None if cache_dir is None else str(cache_dir),
    }
    _write_state(state_path, state)
    _write_manifest(manifest, args=args, instrument=instrument, start=start, end=end, output=output, stats=stats, rows=len(bars), scale=scale)

    if bars.empty:
        print(f"wrote 0 bars to {output}; stats={stats}")
    else:
        print(
            f"wrote {len(bars)} bars to {output} "
            f"({bars['timestamp'].min()} .. {bars['timestamp'].max()}); stats={stats}"
        )
    print(
        "diagnostics: "
        f"cache_hits={stats.cache_hits} http_downloads={stats.http_downloads} "
        f"closure_hours={stats.closure_hours} retry_attempts={stats.retry_attempts} "
        f"retry_recovered_hours={stats.retry_recovered_hours}"
    )
    print(f"wrote manifest to {manifest}")
    return 0


def main() -> int:
    return run_ingest(_build_parser().parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
