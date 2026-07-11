"""Tests for the WP-28 historical data ingestion scripts.

We never hit the network — both CLIs are tested by injecting a fake
`fetch_day` callable into the shared `ingest_range` helper.
"""

from __future__ import annotations

import sys
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd

# Make scripts/ importable.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from _ingest_common import ingest_range, daterange  # noqa: E402
import ingest_dukascopy_ticks as dukascopy  # noqa: E402


def _fake_day_df(symbol: str, day: date) -> pd.DataFrame:
    n = 5
    base = 5000.0 + day.day
    return pd.DataFrame({
        "timestamp": pd.date_range(day.isoformat(), periods=n, freq="1min"),
        "open": np.full(n, base),
        "high": np.full(n, base + 1),
        "low": np.full(n, base - 1),
        "close": np.full(n, base),
        "volume": np.full(n, 100.0),
    })


def test_daterange_inclusive():
    days = daterange(date(2024, 1, 1), date(2024, 1, 3))
    assert days == [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)]


def test_ingest_writes_per_day_parquet(tmp_path):
    result = ingest_range(
        symbol="ES",
        start=date(2024, 1, 1),
        end=date(2024, 1, 3),
        out_dir=tmp_path,
        fetch_day=_fake_day_df,
    )
    assert len(result.written) == 3
    assert result.skipped == []
    for d in [date(2024, 1, 1), date(2024, 1, 2), date(2024, 1, 3)]:
        p = tmp_path / "ES" / f"{d.isoformat()}.parquet"
        assert p.exists()
        df = pd.read_parquet(p)
        assert {"timestamp", "open", "high", "low", "close", "volume"} <= set(df.columns)


def test_ingest_is_idempotent(tmp_path):
    ingest_range(
        symbol="ES",
        start=date(2024, 1, 1),
        end=date(2024, 1, 2),
        out_dir=tmp_path,
        fetch_day=_fake_day_df,
    )
    # Second run should skip every day.
    result = ingest_range(
        symbol="ES",
        start=date(2024, 1, 1),
        end=date(2024, 1, 2),
        out_dir=tmp_path,
        fetch_day=_fake_day_df,
    )
    assert result.written == []
    assert len(result.skipped) == 2


def test_ingest_records_failures(tmp_path):
    def boom(symbol, day):
        raise RuntimeError("fetcher down")
    result = ingest_range(
        symbol="ES",
        start=date(2024, 1, 1),
        end=date(2024, 1, 2),
        out_dir=tmp_path,
        fetch_day=boom,
    )
    assert result.written == []
    assert len(result.failed) == 2


def test_ingest_validates_columns(tmp_path):
    def bad_columns(symbol, day):
        return pd.DataFrame({"timestamp": [day], "close": [1.0]})  # missing OHL+volume
    result = ingest_range(
        symbol="ES",
        start=date(2024, 1, 1),
        end=date(2024, 1, 1),
        out_dir=tmp_path,
        fetch_day=bad_columns,
    )
    # Validation error → counted as failed, not silently written.
    assert result.failed == [date(2024, 1, 1)]
    assert result.written == []


def test_databento_main_smoke(tmp_path, monkeypatch):
    """Drive the CLI's main() with a monkeypatched fetcher."""
    import ingest_databento as mod  # type: ignore
    monkeypatch.setattr(mod, "_default_fetch_day", _fake_day_df)
    rc = mod.main([
        "--symbol", "ES",
        "--start", "2024-01-01",
        "--end", "2024-01-02",
        "--out", str(tmp_path),
    ])
    assert rc == 0
    assert (tmp_path / "ES" / "2024-01-01.parquet").exists()


def test_tardis_main_smoke(tmp_path, monkeypatch):
    import ingest_tardis as mod  # type: ignore
    monkeypatch.setattr(mod, "_default_fetch_day", _fake_day_df)
    rc = mod.main([
        "--symbol", "BTCUSDT",
        "--start", "2024-01-01",
        "--end", "2024-01-01",
        "--out", str(tmp_path),
    ])
    assert rc == 0
    assert (tmp_path / "BTCUSDT" / "2024-01-01.parquet").exists()


def test_dukascopy_refuses_implicit_overwrite(tmp_path):
    output = tmp_path / "5m-ask.parquet"
    existing = pd.DataFrame({
        "timestamp": pd.to_datetime(["2024-01-01T00:00:00Z"]),
        "price_type": ["ASK"],
        "close": [1.0],
    })
    replacement = pd.DataFrame({
        "timestamp": pd.to_datetime(["2024-01-02T00:00:00Z"]),
        "price_type": ["ASK"],
        "close": [2.0],
    })
    existing.to_parquet(output, index=False)

    try:
        dukascopy._merge_existing(replacement, output, append=False, overwrite=False, price_type="ASK")
    except ValueError as exc:
        assert "refusing to overwrite existing Dukascopy parquet" in str(exc)
    else:
        raise AssertionError("expected implicit overwrite to be refused")


def test_dukascopy_append_still_merges_and_deduplicates(tmp_path):
    output = tmp_path / "5m-ask.parquet"
    existing = pd.DataFrame({
        "timestamp": pd.to_datetime(["2024-01-01T00:00:00Z"]),
        "price_type": ["ASK"],
        "close": [1.0],
    })
    update = pd.DataFrame({
        "timestamp": pd.to_datetime(["2024-01-01T00:00:00Z", "2024-01-02T00:00:00Z"]),
        "price_type": ["ASK", "ASK"],
        "close": [1.5, 2.0],
    })
    existing.to_parquet(output, index=False)

    merged = dukascopy._merge_existing(update, output, append=True, overwrite=False, price_type="ASK")

    assert len(merged) == 2
    assert list(merged["close"]) == [1.5, 2.0]


def test_dukascopy_raw_cache_avoids_network(tmp_path, monkeypatch):
    hour = datetime(2024, 1, 2, 3, tzinfo=UTC)
    cache_dir = tmp_path / "cache"
    dukascopy._write_cached_hour(cache_dir, "USA500IDXUSD", hour, b"cached-bi5")

    def fail_fetch(*args, **kwargs):
        raise AssertionError("network fetch should not be called for cached hour")

    monkeypatch.setattr(dukascopy, "_fetch_hour", fail_fetch)

    result = dukascopy._fetch_raw_hour(
        "USA500IDXUSD",
        hour,
        timeout_seconds=1,
        cache_dir=cache_dir,
        max_retries=3,
        backoff_base_seconds=0,
        sleep=False,
    )

    assert result.payload == b"cached-bi5"
    assert result.source == "cache"


def test_dukascopy_market_closure_filter_is_conservative():
    saturday = datetime(2024, 1, 6, 12, tzinfo=UTC)
    sunday_before_open = datetime(2024, 1, 7, 12, tzinfo=UTC)
    monday_session = datetime(2024, 1, 8, 12, tzinfo=UTC)

    assert dukascopy._is_market_closure_hour("USA500IDXUSD", saturday)
    assert dukascopy._is_market_closure_hour("USA500IDXUSD", sunday_before_open)
    assert not dukascopy._is_market_closure_hour("USA500IDXUSD", monday_session)


def test_dukascopy_parser_has_pull_reliability_knobs():
    args = dukascopy._build_parser().parse_args([
        "--symbol",
        "USA500IDXUSD",
        "--start",
        "2024-01-01",
        "--end",
        "2024-01-02",
        "--workers",
        "4",
        "--max-fetch-retries",
        "5",
        "--raw-cache-dir",
        "custom-cache",
    ])

    assert args.workers == 4
    assert args.max_fetch_retries == 5
    assert args.raw_cache_dir == "custom-cache"
    assert not args.no_raw_cache
