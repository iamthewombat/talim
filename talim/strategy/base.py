"""Base strategy abstract class."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from talim.models.bar import OHLCVBar
from talim.models.signal import Signal
from talim.strategy.params import ParamSpec, validate_param_dict
from talim.strategy.validation import ValidationResult, default_validate_signal


class BaseStrategy(ABC):
    """Abstract base for all Talim strategies.

    The same on_bar implementation runs in both live and backtest modes.

    Subclasses declare tunable parameters in ``PARAMS`` (a list of
    :class:`ParamSpec`). When ``PARAMS`` is non-empty, ``load_params``
    validates and coerces the incoming dict against the schema and raises
    :class:`StrategyParamError` on any violation. Strategies without a
    declared schema fall back to the legacy permissive ``setattr`` behaviour.
    """

    PARAMS: list[ParamSpec] = []

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique strategy identifier (e.g. 'momentum-US500')."""
        ...

    @abstractmethod
    def on_bar(self, bar: OHLCVBar) -> Signal | None:
        """Process a new bar. Return a Signal if entry/exit criteria are met."""
        ...

    def load_params(self, params: dict[str, Any]) -> None:
        """Load or update strategy parameters at runtime.

        If the strategy declares a ``PARAMS`` schema, incoming values are
        validated and coerced against it and unknown keys are rejected.
        Otherwise values are applied only if the attribute already exists on
        the strategy (legacy behaviour preserved for older strategies).
        """
        if self.PARAMS:
            coerced = validate_param_dict(
                params,
                self.PARAMS,
                strategy=self.name,
            )
            for key, value in coerced.items():
                setattr(self, key, value)
            return
        for key, value in params.items():
            if hasattr(self, key):
                setattr(self, key, value)

    def reset(self) -> None:
        """Reset internal state (e.g. between backtest runs)."""
        pass

    def exit_signal(self, bar: OHLCVBar, side: str) -> bool:
        """Condition exit for an open position, checked once per bar close.

        The backtest engine calls this after bracket (stop/target) checks
        while a position is open; returning True closes the position at the
        bar close. Default: no condition exit (brackets only).
        """
        return False

    def validate_signal(
        self,
        signal: Signal,
        bars: list[OHLCVBar],
        *,
        atr: float | None = None,
    ) -> ValidationResult:
        """Return whether a pending HITL signal is still actionable.

        Subclasses should override this for strategy-specific semantics. The
        base implementation is intentionally conservative and checks only
        freshness plus price movement from the original entry in R/ATR terms.
        """
        return default_validate_signal(signal, bars, atr=atr)

    @classmethod
    def params_schema(cls) -> list[dict[str, Any]]:
        """Return the declared parameter schema as a list of JSON-safe dicts."""
        return [spec.to_dict() for spec in cls.PARAMS]

    def current_params(self) -> dict[str, Any]:
        """Return the current values of all declared parameters."""
        return {spec.name: getattr(self, spec.name) for spec in self.PARAMS}

    def current_params_subset(self, keys: list[str]) -> dict[str, Any]:
        """Return current values for a subset of parameter names."""
        return {key: getattr(self, key) for key in keys if hasattr(self, key)}
