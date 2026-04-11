from __future__ import annotations

from dataclasses import dataclass, asdict, field
from datetime import datetime


@dataclass(slots=True)
class Position:
    """An open or closed trading position."""

    instrument: str
    side: str  # "long" or "short"
    qty: float
    entry_price: float
    stop: float
    target: float
    strategy: str
    open_pnl: float = 0.0
    entry_time: datetime | None = None
    position_id: str = ""

    def to_dict(self) -> dict:
        d = asdict(self)
        if self.entry_time is not None:
            d["entry_time"] = self.entry_time.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> Position:
        data = dict(d)
        if isinstance(data.get("entry_time"), str):
            data["entry_time"] = datetime.fromisoformat(data["entry_time"])
        return cls(**data)
