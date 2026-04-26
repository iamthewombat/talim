"""Declarative parameter schemas for strategies (WP-72).

A strategy declares its tunable parameters as a ``PARAMS`` class attribute
holding a list of :class:`ParamSpec`. ``BaseStrategy.load_params`` validates
and coerces incoming dicts against that list and raises
:class:`StrategyParamError` on any violation.

This is the boundary where we reject garbage from the LLM, the operator,
or a backtest CLI invocation — before the strategy gets a chance to run
with nonsense values.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


class StrategyParamError(ValueError):
    """Raised when a proposed parameter value fails validation."""

    def __init__(
        self,
        *,
        strategy: str,
        param: str,
        value: Any,
        reason: str,
    ) -> None:
        self.strategy = strategy
        self.param = param
        self.value = value
        self.reason = reason
        super().__init__(
            f"invalid param '{param}'={value!r} for strategy '{strategy}': {reason}"
        )


@dataclass(frozen=True)
class ParamSpec:
    """Declarative spec for a single strategy parameter.

    - ``type`` is the target Python type; incoming values are coerced to it.
    - ``min`` / ``max`` are inclusive bounds (numeric types only).
    - ``choices`` constrains the value to an explicit allow-list; mutually
      exclusive with ``min``/``max``.
    """

    name: str
    type: type
    default: Any
    min: float | None = None
    max: float | None = None
    choices: tuple[Any, ...] | None = None
    description: str = ""

    def coerce_and_validate(self, value: Any, *, strategy: str) -> Any:
        # Bool must be handled before int because ``bool`` is a subclass of
        # ``int`` in Python — otherwise ``True`` would pass as an int.
        if self.type is bool:
            if isinstance(value, bool):
                coerced = value
            elif isinstance(value, (int, float)) and value in (0, 1):
                coerced = bool(value)
            else:
                raise StrategyParamError(
                    strategy=strategy,
                    param=self.name,
                    value=value,
                    reason="must be a boolean",
                )
        elif self.type is int:
            if isinstance(value, bool):
                raise StrategyParamError(
                    strategy=strategy,
                    param=self.name,
                    value=value,
                    reason="must be an integer, not a bool",
                )
            if isinstance(value, int):
                coerced = value
            elif isinstance(value, float) and value.is_integer():
                coerced = int(value)
            else:
                raise StrategyParamError(
                    strategy=strategy,
                    param=self.name,
                    value=value,
                    reason="must be an integer",
                )
        elif self.type is float:
            if isinstance(value, bool):
                raise StrategyParamError(
                    strategy=strategy,
                    param=self.name,
                    value=value,
                    reason="must be a number, not a bool",
                )
            if isinstance(value, (int, float)):
                coerced = float(value)
            else:
                raise StrategyParamError(
                    strategy=strategy,
                    param=self.name,
                    value=value,
                    reason="must be a number",
                )
        elif self.type is str:
            if not isinstance(value, str):
                raise StrategyParamError(
                    strategy=strategy,
                    param=self.name,
                    value=value,
                    reason="must be a string",
                )
            coerced = value
        else:
            if not isinstance(value, self.type):
                raise StrategyParamError(
                    strategy=strategy,
                    param=self.name,
                    value=value,
                    reason=f"must be {self.type.__name__}",
                )
            coerced = value

        if self.choices is not None:
            if coerced not in self.choices:
                raise StrategyParamError(
                    strategy=strategy,
                    param=self.name,
                    value=value,
                    reason=f"must be one of {list(self.choices)}",
                )
        else:
            if self.min is not None and coerced < self.min:
                raise StrategyParamError(
                    strategy=strategy,
                    param=self.name,
                    value=value,
                    reason=f"must be >= {self.min}",
                )
            if self.max is not None and coerced > self.max:
                raise StrategyParamError(
                    strategy=strategy,
                    param=self.name,
                    value=value,
                    reason=f"must be <= {self.max}",
                )

        return coerced

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "type": self.type.__name__,
            "default": self.default,
            "min": self.min,
            "max": self.max,
            "choices": list(self.choices) if self.choices is not None else None,
            "description": self.description,
        }


def validate_param_dict(
    params: dict[str, Any],
    schema: list[ParamSpec],
    *,
    strategy: str,
) -> dict[str, Any]:
    """Validate and coerce a param dict against a schema.

    Unknown keys are rejected. Missing keys are allowed (partial updates).
    """
    by_name: dict[str, ParamSpec] = {spec.name: spec for spec in schema}
    out: dict[str, Any] = {}
    for key, value in params.items():
        spec = by_name.get(key)
        if spec is None:
            raise StrategyParamError(
                strategy=strategy,
                param=key,
                value=value,
                reason="unknown parameter",
            )
        out[key] = spec.coerce_and_validate(value, strategy=strategy)
    return out
