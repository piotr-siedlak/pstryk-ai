"""Learning model parameters from measurements (each part can be disabled).

* Heat-loss model of a storage: in hours without heating (heat-pump and heater
  power ≈ 0) the temperature change satisfies
      C·ΔT = −(k·max(0, T_base − T_out) + U·(T − 20))
  ``k`` (building demand per K) and ``U`` (standby losses) are fitted by
  non-negative least squares.
* Hot-water draw profile: in hours without heating, the energy drop beyond
  standby losses is attributed to hot-water use, averaged per hour of day.
* Heat-pump COP: in heating hours with known electric energy, the delivered
  heat C·ΔT + losses (+ demand) divided by the electric energy; the median ratio
  to the model COP calibrates the COP model.

Learned values are applied only after enough samples and when they are
plausible; otherwise the configured values are used.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import math
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from .const import LOCAL_TZ

TZ = ZoneInfo(LOCAL_TZ)
MIN_LOSS_SAMPLES = 36
MIN_COP_SAMPLES = 12
MAX_SAMPLES = 24 * 60


@dataclass(slots=True)
class HourSample:
    """One hour of observations for a storage."""

    start: datetime
    t_start: float
    t_end: float
    t_out: float
    hp_kwh: float | None  # electric energy of the heat pump in this hour (None = unknown)
    heater_kwh: float | None
    heating_by_plan: bool  # fallback when no power measurement exists

    def to_list(self) -> list[Any]:
        return [
            self.start.isoformat(),
            self.t_start,
            self.t_end,
            self.t_out,
            self.hp_kwh,
            self.heater_kwh,
            self.heating_by_plan,
        ]

    @classmethod
    def from_list(cls, data: list[Any]) -> HourSample:
        return cls(datetime.fromisoformat(data[0]), *data[1:])  # type: ignore[arg-type]

    @property
    def idle(self) -> bool:
        if self.hp_kwh is not None or self.heater_kwh is not None:
            return (self.hp_kwh or 0.0) < 0.05 and (self.heater_kwh or 0.0) < 0.05
        return not self.heating_by_plan


def fit_losses(samples: list[HourSample], capacity: float, base_t: float) -> dict[str, float] | None:
    """Fit k (kW/K building demand) and U (kW/K standby) on idle hours."""
    rows = [s for s in samples if s.idle and s.t_end <= s.t_start + 0.2]
    if len(rows) < MIN_LOSS_SAMPLES:
        return None
    x1 = [max(0.0, base_t - s.t_out) for s in rows]
    x2 = [max(0.0, (s.t_start + s.t_end) / 2 - 20.0) for s in rows]
    y = [max(0.0, (s.t_start - s.t_end) * capacity) for s in rows]
    # 2x2 normal equations without intercept, then clip to non-negative
    a11 = sum(v * v for v in x1)
    a22 = sum(v * v for v in x2)
    a12 = sum(a * b for a, b in zip(x1, x2, strict=True))
    b1 = sum(a * b for a, b in zip(x1, y, strict=True))
    b2 = sum(a * b for a, b in zip(x2, y, strict=True))
    det = a11 * a22 - a12 * a12
    if abs(det) < 1e-9:
        k = b1 / a11 if a11 > 0 else 0.0
        u = 0.0
    else:
        k = (b1 * a22 - b2 * a12) / det
        u = (a11 * b2 - a12 * b1) / det
    if k < 0:
        k, u = 0.0, (b2 / a22 if a22 > 0 else 0.0)
    if u < 0:
        u, k = 0.0, (b1 / a11 if a11 > 0 else 0.0)
    pred = [k * a + u * b for a, b in zip(x1, x2, strict=True)]
    ss_res = sum((p - t) ** 2 for p, t in zip(pred, y, strict=True))
    mean_y = sum(y) / len(y)
    ss_tot = sum((t - mean_y) ** 2 for t in y) or 1e-9
    r2 = 1 - ss_res / ss_tot
    if not (0 <= k <= 5 and 0 <= u <= 0.2) or math.isnan(r2):
        return None
    return {"building_kw_per_k": round(k, 4), "loss_kw_per_k": round(u, 5), "r2": round(r2, 3), "samples": len(rows)}


def fit_draw_profile(samples: list[HourSample], capacity: float, loss_kw_per_k: float) -> list[float] | None:
    """Average hot-water draw (kWh_th) per local hour of day."""
    buckets: dict[int, list[float]] = {h: [] for h in range(24)}
    for s in samples:
        if not s.idle:
            continue
        loss = loss_kw_per_k * max(0.0, (s.t_start + s.t_end) / 2 - 20.0)
        draw = max(0.0, (s.t_start - s.t_end) * capacity - loss)
        buckets[s.start.astimezone(TZ).hour].append(draw)
    if sum(len(v) for v in buckets.values()) < MIN_LOSS_SAMPLES or any(not v for v in buckets.values()):
        return None
    return [round(sum(v) / len(v), 4) for _, v in sorted(buckets.items())]


def fit_cop_ratio(samples: list[HourSample], capacity: float, loss_kw_per_k: float, model_cop) -> float | None:
    """Median ratio measured/model COP in heat-pump hours with metered energy."""
    ratios = []
    for s in samples:
        if not s.hp_kwh or s.hp_kwh < 0.2 or (s.heater_kwh or 0) > 0.05:
            continue
        loss = loss_kw_per_k * max(0.0, (s.t_start + s.t_end) / 2 - 20.0)
        heat = (s.t_end - s.t_start) * capacity + loss
        if heat <= 0:
            continue
        measured = heat / s.hp_kwh
        modelled = model_cop(s.t_out, (s.t_start + s.t_end) / 2 + 5.0)
        if modelled > 0 and 0.3 < measured / modelled < 3:
            ratios.append(measured / modelled)
    if len(ratios) < MIN_COP_SAMPLES:
        return None
    return round(max(0.5, min(1.5, median(ratios))), 3)


@dataclass
class LearningStore:
    samples: dict[str, list[HourSample]] = field(default_factory=dict)
    results: dict[str, dict[str, Any]] = field(default_factory=dict)

    def add(self, storage: str, sample: HourSample) -> None:
        rows = self.samples.setdefault(storage, [])
        rows.append(sample)
        del rows[:-MAX_SAMPLES]

    def to_dict(self) -> dict[str, Any]:
        return {
            "samples": {k: [s.to_list() for s in v] for k, v in self.samples.items()},
            "results": self.results,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> LearningStore:
        data = data or {}
        store = cls()
        for k, rows in (data.get("samples") or {}).items():
            try:
                store.samples[k] = [HourSample.from_list(r) for r in rows]
            except (TypeError, ValueError):
                continue
        store.results = dict(data.get("results") or {})
        return store
