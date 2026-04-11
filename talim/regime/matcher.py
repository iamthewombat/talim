"""Find historical sessions with similar regime fingerprints."""

from __future__ import annotations

from datetime import date

import numpy as np

from talim.regime.calendar import MacroCalendar

# Architecture §7.2 — minimum number of historical candidates that must remain
# after domain filtering before the matcher will return a result. Below this
# floor we return None so the caller can fall back to a wider strategy.
MIN_CANDIDATES = 30


def find_similar_sessions(
    fingerprint: np.ndarray,
    library_features: np.ndarray,
    library_dates: list[date],
    threshold: float = 0.3,
    max_results: int = 20,
    *,
    macro_calendar: MacroCalendar | None = None,
    session_type: str | None = None,
    library_session_types: list[str] | None = None,
    min_candidates: int = MIN_CANDIDATES,
    enforce_min: bool = False,
) -> list[date] | None:
    """Find sessions whose fingerprints are within `threshold` Euclidean distance.

    Domain filters (architecture §7.2):
    - macro_calendar: drop dates flagged as high-impact macro events
    - session_type / library_session_types: only match same session type
    - enforce_min: when True, return None if fewer than `min_candidates`
      survive filtering (signals to caller that the match is unreliable)

    Returns the matching dates sorted closest-first, or None when
    `enforce_min` is set and the candidate pool is too small.
    """
    if library_features.shape[0] == 0:
        return None if enforce_min else []

    n = library_features.shape[0]
    keep = np.ones(n, dtype=bool)

    if macro_calendar is not None:
        for i, d in enumerate(library_dates):
            if macro_calendar.is_macro_event(d):
                keep[i] = False

    if session_type is not None and library_session_types is not None:
        for i, st in enumerate(library_session_types):
            if st != session_type:
                keep[i] = False

    surviving = int(keep.sum())
    if enforce_min and surviving < min_candidates:
        return None

    if surviving == 0:
        return []

    # Euclidean distances (vectorised), restricted to survivors.
    diffs = library_features - fingerprint.reshape(1, -1)
    distances = np.linalg.norm(diffs, axis=1)
    distances[~keep] = np.inf

    mask = distances <= threshold
    matching_indices = np.where(mask)[0]

    if len(matching_indices) == 0:
        return []

    sorted_order = matching_indices[np.argsort(distances[matching_indices])]
    sorted_order = sorted_order[:max_results]

    return [library_dates[i] for i in sorted_order]
