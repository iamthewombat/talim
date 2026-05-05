from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import date


@dataclass(frozen=True, slots=True)
class BacktestRequest:
    """Request to run a backtest for a strategy."""

    strategy_name: str
    instrument: str = "ES"
    timeframe: str | None = None
    param_variants: list[dict] = field(default_factory=list)
    matched_dates: list[date] = field(default_factory=list)
    data_dir: str = "data"
    engine: str = "on_bar"  # WP-29: "on_bar" (default) | "vectorbt"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["matched_dates"] = [dt.isoformat() for dt in self.matched_dates]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> BacktestRequest:
        data = dict(d)
        data["matched_dates"] = [
            date.fromisoformat(dt) if isinstance(dt, str) else dt
            for dt in data.get("matched_dates", [])
        ]
        return cls(**data)


@dataclass(frozen=True, slots=True)
class BacktestResult:
    """Results from a backtest run."""

    strategy_name: str
    net_pnl: float
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    total_trades: int
    param_variant: dict = field(default_factory=dict)
    matched_dates: list[date] = field(default_factory=list)
    return_pct: float = 0.0
    sortino_ratio: float = 0.0
    profit_factor: float = 0.0
    period_start: str = ""
    period_end: str = ""
    status: str = "completed"
    artifact_path: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        d["matched_dates"] = [dt.isoformat() for dt in self.matched_dates]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> BacktestResult:
        data = dict(d)
        data["matched_dates"] = [
            date.fromisoformat(dt) if isinstance(dt, str) else dt
            for dt in data.get("matched_dates", [])
        ]
        return cls(**data)
