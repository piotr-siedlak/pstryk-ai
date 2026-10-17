"""Optimization profile and result models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, time
from typing import Any

from .price_slot import iso


@dataclass(slots=True)
class DeviceProfile:
    """A flexible electrical load to schedule."""

    name: str
    power_kw: float = 1.0
    duration_h: int = 2
    min_run_h: int = 1
    min_off_h: int = 0
    allowed_start: time | None = None  # daily allowed operating window (local)
    allowed_end: time | None = None
    earliest_start: datetime | None = None
    deadline: datetime | None = None
    priority: int = 5
    max_price: float | None = None
    target: float | None = None  # temperature or SOC target, informative
    efficiency: float = 1.0
    required_energy_kwh: float | None = None
    enabled: bool = True
    consecutive: bool = False
    temperature_topic: str | None = None  # exact MQTT topic with the current value (°C or SOC %)
    temperature_key: str | None = None  # JSON key/path when the payload is JSON

    @property
    def slug(self) -> str:
        return "".join(c if c.isalnum() else "_" for c in self.name.lower()).strip("_")

    @property
    def required_hours(self) -> int:
        if self.required_energy_kwh and self.power_kw > 0:
            hours = self.required_energy_kwh / (self.power_kw * max(self.efficiency, 0.01))
            return max(1, int(-(-hours // 1)))
        return max(1, self.duration_h)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("allowed_start", "allowed_end"):
            value = getattr(self, key)
            data[key] = value.strftime("%H:%M") if value else None
        data["earliest_start"] = iso(self.earliest_start)
        data["deadline"] = iso(self.deadline)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeviceProfile:
        from .price_slot import parse_iso

        def _time(value: Any) -> time | None:
            if not value:
                return None
            if isinstance(value, time):
                return value
            parts = [int(p) for p in str(value).split(":")[:2]]
            return time(parts[0] % 24, parts[1] if len(parts) > 1 else 0)

        def _dt(value: Any) -> datetime | None:
            if not value:
                return None
            if isinstance(value, datetime):
                return value
            return parse_iso(str(value))

        return cls(
            name=str(data["name"]),
            power_kw=float(data.get("power_kw", 1.0)),
            duration_h=int(data.get("duration_h", 2)),
            min_run_h=int(data.get("min_run_h", 1)),
            min_off_h=int(data.get("min_off_h", 0)),
            allowed_start=_time(data.get("allowed_start")),
            allowed_end=_time(data.get("allowed_end")),
            earliest_start=_dt(data.get("earliest_start")),
            deadline=_dt(data.get("deadline")),
            priority=int(data.get("priority", 5)),
            max_price=None if data.get("max_price") in (None, "") else float(data["max_price"]),
            target=None if data.get("target") in (None, "") else float(data["target"]),
            efficiency=float(data.get("efficiency", 1.0)),
            required_energy_kwh=(
                None if data.get("required_energy_kwh") in (None, "") else float(data["required_energy_kwh"])
            ),
            enabled=bool(data.get("enabled", True)),
            consecutive=bool(data.get("consecutive", False)),
            temperature_topic=(str(data.get("temperature_topic") or data.get("value_topic") or "").strip() or None),
            temperature_key=(str(data.get("temperature_key") or data.get("value_key") or "").strip() or None),
        )


@dataclass(slots=True)
class Window:
    """A contiguous (or not) set of selected slots."""

    start: datetime
    end: datetime
    average_price: float
    total_cost: float | None = None
    slots: list[datetime] = field(default_factory=list)
    confirmed_share: float = 1.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": iso(self.start),
            "end": iso(self.end),
            "average_price": round(self.average_price, 5),
            "total_cost": None if self.total_cost is None else round(self.total_cost, 4),
            "hours": [iso(s) for s in self.slots],
            "confirmed_share": round(self.confirmed_share, 3),
        }


@dataclass(slots=True)
class DeviceSchedule:
    profile: str
    slots: list[datetime]
    expected_cost: float | None
    expected_energy_kwh: float
    feasible: bool
    reason: str
    next_start: datetime | None = None
    next_stop: datetime | None = None
    current_value: float | None = None
    target: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile,
            "current_value": self.current_value,
            "target": self.target,
            "hours": [iso(s) for s in self.slots],
            "expected_cost": None if self.expected_cost is None else round(self.expected_cost, 4),
            "expected_energy_kwh": round(self.expected_energy_kwh, 3),
            "feasible": self.feasible,
            "reason": self.reason,
            "next_start": iso(self.next_start),
            "next_stop": iso(self.next_stop),
        }


@dataclass(slots=True)
class BufferStep:
    start: datetime
    heat_fraction: float
    temperature_start: float
    temperature_end: float
    electric_kwh: float
    thermal_kwh: float
    price: float
    cop: float
    cost: float
    source: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": iso(self.start),
            "heat": round(self.heat_fraction, 2),
            "t_start": round(self.temperature_start, 2),
            "t_end": round(self.temperature_end, 2),
            "electric_kwh": round(self.electric_kwh, 3),
            "thermal_kwh": round(self.thermal_kwh, 3),
            "price": round(self.price, 5),
            "cop": round(self.cop, 2),
            "cost": round(self.cost, 4),
            "source": self.source,
        }


@dataclass(slots=True)
class BufferPlan:
    """Thermal storage plan (advisory)."""

    generated_at: datetime
    valid_until: datetime
    should_heat: bool
    target_temperature: float
    recommended_start: datetime | None
    recommended_stop: datetime | None
    recommended_duration_h: float
    expected_energy_kwh: float
    expected_cost_pln: float
    expected_savings_pln: float
    next_heating_window: dict[str, Any] | None
    thermal_energy_target_kwh: float
    optimization_confidence: float
    optimization_reason: str
    mode: str = "advisory"
    feasible: bool = True
    steps: list[BufferStep] = field(default_factory=list)

    def to_dict(self, include_steps: bool = True) -> dict[str, Any]:
        data = {
            "generated_at": iso(self.generated_at),
            "valid_until": iso(self.valid_until),
            "should_heat": self.should_heat,
            "target_temperature": round(self.target_temperature, 1),
            "recommended_start": iso(self.recommended_start),
            "recommended_stop": iso(self.recommended_stop),
            "recommended_duration": round(self.recommended_duration_h, 2),
            "expected_energy_kwh": round(self.expected_energy_kwh, 3),
            "expected_cost_pln": round(self.expected_cost_pln, 3),
            "expected_savings_pln": round(self.expected_savings_pln, 3),
            "next_heating_window": self.next_heating_window,
            "thermal_energy_target_kwh": round(self.thermal_energy_target_kwh, 3),
            "optimization_confidence": round(self.optimization_confidence, 3),
            "optimization_reason": self.optimization_reason,
            "mode": self.mode,
            "feasible": self.feasible,
        }
        if include_steps:
            data["schedule"] = [s.to_dict() for s in self.steps]
        return data
