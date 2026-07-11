#!/usr/bin/env python3
"""Probe Dukascopy hourly BI5 availability for one or more symbols.

This is intentionally light-touch: it checks a few representative hours per day
and records the first/last non-empty hourly BI5 file found. Use it to choose
safe year/month batches before running the heavier tick importer.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta
import calendar
from pathlib import Path
import subprocess
import time

from ingest_dukascopy_ticks import _dukascopy_url


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--symbol", action="append", required=True, help="Dukascopy symbol. Repeatable.")
    parser.add_argument("--start-year", type=int, required=True)
    parser.add_argument("--end-year", type=int, required=True, help="Inclusive end year")
    parser.add_argument("--hours", default="0,8,16", help="Comma-separated UTC hours to probe per day")
    parser.add_argument("--days-per-month", type=int, default=10, help="Probe first N calendar days of each month")
    parser.add_argument(
        "--weekdays-only",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip Saturdays/Sundays when probing (--no-weekdays-only to include them)",
    )
    parser.add_argument("--timeout-seconds", type=float, default=8.0)
    parser.add_argument("--sleep-seconds", type=float, default=0.5, help="Delay between probes to avoid Dukascopy throttling")
    parser.add_argument("--output", default="data/backtest/dukascopy-coverage.json")
    return parser


def _probe_hour(symbol: str, hour: datetime, *, timeout_seconds: float) -> str:
    # Use curl for probes because Dukascopy sometimes leaves Python urllib reads
    # hanging on absent/awkward index hours. A one-byte range is enough to prove
    # that the BI5 file exists and is non-empty.
    cmd = [
        "curl",
        "--http1.1",
        "-L",
        "--max-time",
        str(timeout_seconds),
        "-A",
        "talim-dukascopy-coverage/1.0",
        "-sS",
        "-w",
        "%{http_code} %{size_download}",
        "-o",
        "/dev/null",
        "-r",
        "0-0",
        _dukascopy_url(symbol, hour),
    ]
    result = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if result.returncode == 28:
        return "timeout"
    if result.returncode != 0:
        return f"error:curl{result.returncode}"
    parts = result.stdout.strip().split()
    if len(parts) != 2:
        return "error:curl-output"
    status, size_text = parts
    if status == "404":
        return "missing"
    try:
        size = int(size_text)
    except ValueError:
        size = 0
    if status in {"200", "206"} and size > 0:
        return "available"
    if status in {"200", "206"}:
        return "empty"
    return f"error:http{status}"


def _scan_symbol(symbol: str, *, start_year: int, end_year: int, hours: list[int], days_per_month: int, timeout_seconds: float, sleep_seconds: float, weekdays_only: bool = True) -> dict:
    available: list[str] = []
    counts = {"available": 0, "missing": 0, "empty": 0, "error": 0}
    monthly: dict[str, str] = {}
    for year in range(start_year, end_year + 1):
        for month in range(1, 13):
            month_key = f"{year:04d}-{month:02d}"
            month_status = "missing"
            _, last_day = calendar.monthrange(year, month)
            for day in range(1, min(days_per_month, last_day) + 1):
                probe_date = datetime(year, month, day, tzinfo=UTC)
                if weekdays_only and probe_date.weekday() >= 5:
                    continue
                for hour_num in hours:
                    hour = datetime(year, month, day, hour_num, tzinfo=UTC)
                    status = _probe_hour(symbol, hour, timeout_seconds=timeout_seconds)
                    if status == "timeout" or status.startswith("error:"):
                        counts["error"] += 1
                    else:
                        counts[status] += 1
                    if status == "available":
                        value = hour.isoformat().replace("+00:00", "Z")
                        available.append(value)
                        month_status = "available"
                        break
                    if sleep_seconds > 0:
                        time.sleep(sleep_seconds)
                    if status == "empty" and month_status == "missing":
                        month_status = "empty"
                    elif status.startswith("error:") and month_status == "missing":
                        month_status = status
                if month_status == "available":
                    break
            monthly[month_key] = month_status
            print(f"{symbol} {month_key}: {month_status}", flush=True)
    return {
        "symbol": symbol,
        "first_available_hour": min(available) if available else None,
        "last_available_hour": max(available) if available else None,
        "available_probe_count": len(available),
        "probe_counts": counts,
        "monthly": monthly,
    }


def main() -> int:
    args = _build_parser().parse_args()
    if args.start_year > args.end_year:
        raise ValueError("--start-year must be <= --end-year")
    hours = [int(part) for part in args.hours.split(",") if part.strip()]
    for hour in hours:
        if hour < 0 or hour > 23:
            raise ValueError("--hours entries must be 0..23")
    result = {
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "start_year": args.start_year,
        "end_year": args.end_year,
        "hours": hours,
        "days_per_month": args.days_per_month,
        "symbols": [],
        "notes": [
            "Probe checks a subset of hours/days, so first_available_hour is an approximate floor until full import confirms it.",
            "Dukascopy index files can be absent on holidays/weekends and during out-of-session hours.",
        ],
    }
    for symbol in args.symbol:
        result["symbols"].append(
            _scan_symbol(
                symbol,
                start_year=args.start_year,
                end_year=args.end_year,
                hours=hours,
                days_per_month=max(1, args.days_per_month),
                timeout_seconds=args.timeout_seconds,
                sleep_seconds=args.sleep_seconds,
                weekdays_only=args.weekdays_only,
            )
        )
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(f"wrote coverage scan to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
