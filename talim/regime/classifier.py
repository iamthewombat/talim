"""Regime classification using k-means clustering."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from sklearn.cluster import KMeans

# Default regime labels mapped to cluster indices (assigned after fitting)
REGIME_LABELS = ["momentum", "mean_reversion", "high_vol", "ranging"]


@dataclass
class RegimeClassifier:
    """Wraps a fitted k-means model for regime classification."""

    n_clusters: int = 4
    labels: list[str] = field(default_factory=lambda: list(REGIME_LABELS))
    _model: KMeans | None = field(default=None, repr=False)
    _centroids: np.ndarray | None = field(default=None, repr=False)

    @property
    def is_fitted(self) -> bool:
        return self._model is not None

    def fit(self, fingerprints: np.ndarray) -> None:
        """Fit the classifier on a matrix of fingerprints (n_samples, 6)."""
        self._model = KMeans(n_clusters=self.n_clusters, random_state=42, n_init=10)
        self._model.fit(fingerprints)
        self._centroids = self._model.cluster_centers_

    def predict(self, fingerprint: np.ndarray) -> str:
        """Classify a single fingerprint into a regime label."""
        if self._model is None:
            raise RuntimeError("Classifier not fitted. Call fit() first.")
        fp = fingerprint.reshape(1, -1)
        cluster_idx = int(self._model.predict(fp)[0])
        return self.labels[cluster_idx % len(self.labels)]

    @property
    def centroids(self) -> np.ndarray:
        if self._centroids is None:
            raise RuntimeError("Classifier not fitted.")
        return self._centroids


def fit_classifier(fingerprints: np.ndarray, n_clusters: int = 4) -> RegimeClassifier:
    """Convenience: fit and return a RegimeClassifier."""
    clf = RegimeClassifier(n_clusters=n_clusters)
    clf.fit(fingerprints)
    return clf


def classify_regime(fingerprint: np.ndarray, classifier: RegimeClassifier) -> str:
    """Classify a single fingerprint using a pre-fitted classifier."""
    return classifier.predict(fingerprint)
