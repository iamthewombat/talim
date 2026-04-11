"""Regime detection engine — fingerprinting, classification, and session matching."""

from talim.regime.fingerprint import compute_fingerprint, compute_adx, compute_atr
from talim.regime.classifier import classify_regime, fit_classifier, RegimeClassifier
from talim.regime.matcher import find_similar_sessions
from talim.regime.library import build_library, update_library

__all__ = [
    "compute_fingerprint",
    "compute_adx",
    "compute_atr",
    "classify_regime",
    "fit_classifier",
    "RegimeClassifier",
    "find_similar_sessions",
    "build_library",
    "update_library",
]
