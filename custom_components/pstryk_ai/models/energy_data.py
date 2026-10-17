"""Pstryk customer data model (prices, meter values, costs)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .price_slot import PriceSlot, iso


@dataclass(slots=True)
class MeterFrame:
    """One hourly/daily frame of meter and cost data as returned by Pstryk."""

    start: datetime
    end: datetime
    import_kwh: float | None = None
    export_kwh: float | None = None
    balance_kwh: float | None = None
    # Raw cost metric dictionary preserved verbatim (field names per API docs).
    cost: dict[str, Any] = field(default_factory=dict)
    is_live: bool = False

    @property
    def import_cost(self) -> float | None:
        """Gross energy import cost (``energy_import_cost`` or legacy key)."""
        for key in ("energy_import_cost", "total_cost", "fae_cost"):
            if self.cost.get(key) is not None:
                return float(self.cost[key])
        return None

    @property
    def sold_value(self) -> float | None:
        value = self.cost.get("energy_sold_value")
        return None if value is None else float(value)

    @property
    def balance_value(self) -> float | None:
        value = self.cost.get("energy_balance_value")
        if value is not None:
            return float(value)
        if self.import_cost is not None or self.sold_value is not None:
            return (self.sold_value or 0.0) - (self.import_cost or 0.0)
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": iso(self.start),
            "end": iso(self.end),
            "import_kwh": self.import_kwh,
            "export_kwh": self.export_kwh,
            "balance_kwh": self.balance_kwh,
            "import_cost": self.import_cost,
            "sold_value": self.sold_value,
            "balance_value": self.balance_value,
            "is_live": self.is_live,
        }


@dataclass(slots=True)
class PstrykSnapshot:
    """Everything fetched from Pstryk in one coordinated refresh."""

    buy: list[PriceSlot] = field(default_factory=list)
    sell: list[PriceSlot] = field(default_factory=list)
    hourly: list[MeterFrame] = field(default_factory=list)
    daily: list[MeterFrame] = field(default_factory=list)
    summary: dict[str, Any] = field(default_factory=dict)
    monthly_summary: dict[str, Any] = field(default_factory=dict)
    fetched_at: datetime | None = None
    price_fields: dict[str, bool] = field(default_factory=dict)
    tomorrow_confirmed: bool = False

    def sum_frames(self, frames: list[MeterFrame], attr: str) -> float | None:
        values = [getattr(f, attr) for f in frames if getattr(f, attr) is not None]
        return round(sum(values), 4) if values else None
