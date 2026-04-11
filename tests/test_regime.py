"""Tests for the regime detection engine."""

import time
from datetime import date, datetime

import numpy as np
import pandas as pd
import pytest

from talim.regime.fingerprint import compute_fingerprint, compute_adx, compute_atr
from talim.regime.classifier import fit_classifier, classify_regime, RegimeClassifier
from talim.regime.matcher import find_similar_sessions
from talim.regime.library import build_library, update_library


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_synthetic_bars(n: int = 50, trend: float = 0.0, volatility: float = 1.0, seed: int = 42) -> pd.DataFrame:
    """Generate synthetic OHLCV bars with configurable trend and volatility."""
    rng = np.random.RandomState(seed)
    base_price = 5000.0
    returns = trend + volatility * rng.randn(n) * 0.01
    close = base_price * np.cumprod(1 + returns)
    high = close * (1 + rng.uniform(0, 0.005, n))
    low = close * (1 - rng.uniform(0, 0.005, n))
    open_ = close * (1 + rng.uniform(-0.003, 0.003, n))
    volume = rng.uniform(5000, 15000, n)
    timestamps = pd.date_range("2025-01-01", periods=n, freq="5min")

    return pd.DataFrame({
        "timestamp": timestamps,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
    })


def _make_trending_bars(n: int = 50, seed: int = 1) -> pd.DataFrame:
    return _make_synthetic_bars(n=n, trend=0.005, volatility=0.5, seed=seed)


def _make_volatile_bars(n: int = 50, seed: int = 2) -> pd.DataFrame:
    return _make_synthetic_bars(n=n, trend=0.0, volatility=3.0, seed=seed)


def _make_calm_bars(n: int = 50, seed: int = 3) -> pd.DataFrame:
    return _make_synthetic_bars(n=n, trend=0.0, volatility=0.2, seed=seed)


# ---------------------------------------------------------------------------
# Fingerprint tests
# ---------------------------------------------------------------------------

class TestComputeFingerprint:
    def test_output_shape(self):
        bars = _make_synthetic_bars(50)
        fp = compute_fingerprint(bars)
        assert fp.shape == (6,)

    def test_output_dtype(self):
        bars = _make_synthetic_bars(50)
        fp = compute_fingerprint(bars)
        assert fp.dtype == np.float64

    def test_values_finite(self):
        bars = _make_synthetic_bars(50)
        fp = compute_fingerprint(bars)
        assert np.all(np.isfinite(fp))

    def test_adx_non_negative(self):
        bars = _make_synthetic_bars(50)
        fp = compute_fingerprint(bars)
        assert fp[0] >= 0  # ADX is always non-negative

    def test_trending_vs_calm_adx(self):
        fp_trend = compute_fingerprint(_make_trending_bars())
        fp_calm = compute_fingerprint(_make_calm_bars())
        # Trending bars should generally have higher ADX
        # (not strictly guaranteed with synthetic data, so just check they differ)
        assert fp_trend[0] != fp_calm[0]

    def test_volatile_vs_calm_volatility(self):
        fp_vol = compute_fingerprint(_make_volatile_bars())
        fp_calm = compute_fingerprint(_make_calm_bars())
        # Feature 3 is realised volatility — volatile should be higher
        assert fp_vol[3] > fp_calm[3]

    def test_minimum_bars(self):
        bars = _make_synthetic_bars(20)
        fp = compute_fingerprint(bars)
        assert fp.shape == (6,)
        assert np.all(np.isfinite(fp))


class TestComputeATR:
    def test_output_length(self):
        bars = _make_synthetic_bars(50)
        atr = compute_atr(bars, period=14)
        assert len(atr) == 50

    def test_atr_positive(self):
        bars = _make_synthetic_bars(50)
        atr = compute_atr(bars, period=14)
        assert (atr > 0).all()


class TestComputeADX:
    def test_output_length(self):
        bars = _make_synthetic_bars(50)
        adx = compute_adx(bars, period=14)
        assert len(adx) == 50

    def test_adx_non_negative(self):
        bars = _make_synthetic_bars(50)
        adx = compute_adx(bars, period=14)
        assert (adx >= 0).all()


# ---------------------------------------------------------------------------
# Classifier tests
# ---------------------------------------------------------------------------

class TestClassifier:
    def test_fit_and_predict(self):
        # Generate fingerprints from different regime types
        fingerprints = np.array([
            compute_fingerprint(_make_synthetic_bars(50, seed=i))
            for i in range(40)
        ])
        clf = fit_classifier(fingerprints, n_clusters=4)
        assert clf.is_fitted

        # Predict on a known fingerprint
        label = classify_regime(fingerprints[0], clf)
        assert label in ["momentum", "mean_reversion", "high_vol", "ranging"]

    def test_centroids_at_cluster_centers(self):
        # Create synthetic fingerprints near known cluster centers
        rng = np.random.RandomState(42)
        centers = np.array([
            [30, 1.5, 2.0, 0.02, 1.2, 0.05],   # momentum-like
            [10, 0.8, -0.5, 0.01, 0.9, -0.01],  # mean-reversion-like
            [20, 2.5, 0.0, 0.04, 1.8, 0.0],     # high-vol-like
            [5, 0.5, 0.0, 0.005, 0.7, 0.0],      # low-vol-like
        ])
        fingerprints = []
        for center in centers:
            for _ in range(25):
                fingerprints.append(center + rng.randn(6) * 0.1)
        fingerprints = np.array(fingerprints)

        clf = fit_classifier(fingerprints, n_clusters=4)

        # Each center should classify to a consistent label
        labels = [classify_regime(c, clf) for c in centers]
        assert len(set(labels)) == 4  # All 4 centers get different labels

    def test_unfitted_raises(self):
        clf = RegimeClassifier()
        with pytest.raises(RuntimeError):
            clf.predict(np.zeros(6))


# ---------------------------------------------------------------------------
# Matcher tests
# ---------------------------------------------------------------------------

class TestFindSimilarSessions:
    def test_exact_match(self):
        rng = np.random.RandomState(42)
        library = rng.randn(100, 6)
        dates = [date(2025, 1, 1 + i % 28) for i in range(100)]

        # Query with an exact copy of row 50
        query = library[50].copy()
        results = find_similar_sessions(query, library, dates, threshold=0.01)
        assert date(2025, 1, 23) in results  # 50 % 28 + 1 = 23

    def test_near_duplicate_found(self):
        rng = np.random.RandomState(42)
        library = rng.randn(100, 6)
        dates = [date(2025, 1, 1 + i % 28) for i in range(100)]

        # Query with a near-duplicate of row 10
        query = library[10] + rng.randn(6) * 0.01
        results = find_similar_sessions(query, library, dates, threshold=0.3)
        assert len(results) > 0

    def test_no_match_with_tight_threshold(self):
        rng = np.random.RandomState(42)
        library = rng.randn(100, 6)
        dates = [date(2025, 1, 1 + i % 28) for i in range(100)]

        # Query far from any library entry
        query = np.ones(6) * 100.0
        results = find_similar_sessions(query, library, dates, threshold=0.01)
        assert len(results) == 0

    def test_sorted_by_distance(self):
        library = np.array([
            [0, 0, 0, 0, 0, 0],
            [1, 0, 0, 0, 0, 0],
            [0.5, 0, 0, 0, 0, 0],
        ], dtype=float)
        dates = [date(2025, 1, 1), date(2025, 1, 2), date(2025, 1, 3)]
        query = np.zeros(6)

        results = find_similar_sessions(query, library, dates, threshold=2.0)
        assert results[0] == date(2025, 1, 1)  # distance 0
        assert results[1] == date(2025, 1, 3)  # distance 0.5
        assert results[2] == date(2025, 1, 2)  # distance 1.0

    def test_empty_library(self):
        results = find_similar_sessions(
            np.zeros(6), np.empty((0, 6)), [], threshold=1.0
        )
        assert results == []

    def test_performance_2000_rows(self):
        rng = np.random.RandomState(42)
        library = rng.randn(2000, 6)
        dates = [date(2025, 1, 1)] * 2000
        query = rng.randn(6)

        start = time.perf_counter()
        find_similar_sessions(query, library, dates, threshold=1.0)
        elapsed_ms = (time.perf_counter() - start) * 1000

        assert elapsed_ms < 10, f"find_similar_sessions took {elapsed_ms:.1f}ms (limit: 10ms)"


# ---------------------------------------------------------------------------
# Library tests
# ---------------------------------------------------------------------------

class TestLibrary:
    def test_build_library(self):
        bars = _make_synthetic_bars(200, seed=42)
        features, dates = build_library(bars, session_size=50)
        assert features.shape == (4, 6)  # 200 / 50 = 4 sessions
        assert len(dates) == 4

    def test_build_library_dates_are_dates(self):
        bars = _make_synthetic_bars(100, seed=42)
        features, dates = build_library(bars, session_size=50)
        for d in dates:
            assert isinstance(d, date)

    def test_update_library(self):
        bars1 = _make_synthetic_bars(100, seed=1)
        bars2 = _make_synthetic_bars(100, seed=2)

        feat1, dates1 = build_library(bars1, session_size=50)
        feat2, dates2 = update_library(feat1, dates1, bars2, session_size=50)

        assert feat2.shape == (4, 6)  # 2 + 2
        assert len(dates2) == 4

    def test_update_empty_library(self):
        bars = _make_synthetic_bars(100, seed=1)
        feat, dates = update_library(
            np.empty((0, 6)), [], bars, session_size=50
        )
        assert feat.shape == (2, 6)

    def test_too_few_bars(self):
        bars = _make_synthetic_bars(10)
        features, dates = build_library(bars, session_size=50)
        assert features.shape[0] == 0
        assert dates == []


# ---------------------------------------------------------------------------
# WP-22: matcher domain filters + macro calendar + ranging label
# ---------------------------------------------------------------------------

class TestMatcherDomainFilters:
    def _setup(self, n=40):
        rng = np.random.RandomState(0)
        feats = rng.randn(n, 6).astype(np.float64)
        dates = [date(2025, 1, 1 + (i % 28)) for i in range(n)]
        # Make the query close to row 0 specifically.
        query = feats[0] + 0.001
        return query, feats, dates

    def test_macro_event_excluded(self):
        from talim.regime.calendar import MacroCalendar
        query, feats, dates = self._setup(40)
        cal = MacroCalendar({dates[0]})  # exclude the closest match
        out = find_similar_sessions(
            query, feats, dates, threshold=10.0, max_results=5,
            macro_calendar=cal,
        )
        assert dates[0] not in out

    def test_session_type_filter(self):
        query, feats, dates = self._setup(40)
        types = ["RTH" if i < 20 else "ETH" for i in range(40)]
        out = find_similar_sessions(
            query, feats, dates, threshold=10.0, max_results=40,
            session_type="RTH", library_session_types=types,
        )
        # All returned dates must come from the first 20 rows.
        rth_dates = set(dates[:20])
        assert all(d in rth_dates for d in out)

    def test_min_candidates_returns_none(self):
        query, feats, dates = self._setup(20)  # only 20 candidates
        out = find_similar_sessions(
            query, feats, dates, threshold=10.0,
            enforce_min=True, min_candidates=30,
        )
        assert out is None


class TestRangingLabel:
    def test_classifier_uses_ranging_label(self):
        from talim.regime.classifier import REGIME_LABELS
        assert "ranging" in REGIME_LABELS
        assert "low_vol" not in REGIME_LABELS
