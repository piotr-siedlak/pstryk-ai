"""Heat system: several thermal storages sharing one heat pump and a power limit.

Strategy ("priority-sequential MPC"): the storage with priority (hot water by
default) is planned first with the heat pump available in every hour; the second
storage is then planned with the heat pump available only in hours the first
one does not use (switching valve), and with the electric power cap reduced by
what the first one already consumes. This is fast (two 1-D dynamic programs
instead of one 2-D) and matches how a heat pump with a 3-way valve works.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime

from ..models.optimizer import BufferPlan
from ..models.price_slot import PriceSlot, iso
from .heat_pump import CopModel
from .thermal_storage import BufferConfig, plan_buffer

VALVE_BUFFER = "buffer"
VALVE_DHW = "dhw"
VALVE_IDLE = "idle"


@dataclass(slots=True)
class StorageInput:
    cfg: BufferConfig
    current_t: float | None  # mean temperature (None -> fallback)
    stale: bool = False


@dataclass(slots=True)
class HeatSystemPlan:
    plans: dict[str, BufferPlan] = field(default_factory=dict)
    valve: list[tuple[datetime, str]] = field(default_factory=list)
    power_limit_kw: float | None = None

    @property
    def valve_now(self) -> str:
        return self.valve[0][1] if self.valve else VALVE_IDLE

    def valve_records(self) -> list[dict[str, str | None]]:
        return [{"start": iso(t), "position": p} for t, p in self.valve]


def plan_heat_system(
    storages: Mapping[str, StorageInput],
    cop: CopModel,
    *,
    now: datetime,
    slots: Sequence[PriceSlot],
    outdoor_forecast: Mapping[datetime, float],
    shared_hp: bool = True,
    priority: str = VALVE_DHW,
    power_limit_kw: float | None = None,
    other_load_kw: Mapping[datetime, float] | None = None,
    sell_prices: Mapping[datetime, float] | None = None,
    surplus_kwh: Mapping[datetime, float] | None = None,
    advisory: bool = True,
    fallback_reason: Mapping[str, str] | None = None,
) -> HeatSystemPlan:
    """Plan all enabled storages. Keys are storage names ("buffer", "dhw")."""
    hour = now.replace(minute=0, second=0, microsecond=0)
    horizon = [s for s in slots if s.start >= hour]
    other = other_load_kw or {}
    used_elec = [0.0] * len(horizon)
    hp_free = [True] * len(horizon)
    order = sorted(storages, key=lambda k: 0 if k == priority else 1)
    result = HeatSystemPlan(power_limit_kw=power_limit_kw)
    remaining_surplus = dict(surplus_kwh or {})

    for name in order:
        item = storages[name]
        cap = None
        if power_limit_kw is not None:
            cap = [max(0.0, power_limit_kw - other.get(s.start, 0.0) - used_elec[i]) for i, s in enumerate(horizon)]
        stale = item.stale or item.current_t is None
        plan = plan_buffer(
            item.cfg,
            cop,
            now=now,
            current_t=item.current_t if item.current_t is not None else item.cfg.target_t,
            slots=horizon,
            outdoor_forecast=outdoor_forecast,
            advisory=advisory,
            stale=stale,
            hp_available=hp_free if shared_hp else None,
            cap_kw=cap,
            sell_prices=sell_prices,
            surplus_kwh=remaining_surplus,
        )
        plan.name = name
        if stale and fallback_reason and name in fallback_reason:
            plan.optimization_reason = fallback_reason[name]
        for i, step in enumerate(plan.steps):
            if i >= len(horizon):
                break
            used_elec[i] += step.electric_kwh
            if step.hp_kwh > 0 and shared_hp:
                hp_free[i] = False
            start = horizon[i].start
            if start in remaining_surplus:
                remaining_surplus[start] = max(0.0, remaining_surplus[start] - step.electric_kwh)
        result.plans[name] = plan

    # valve position per hour (which storage the heat pump serves)
    n = max((len(p.steps) for p in result.plans.values()), default=0)
    for i in range(n):
        position = VALVE_IDLE
        for name in order:
            steps = result.plans[name].steps
            if i < len(steps) and steps[i].hp_kwh > 0:
                position = VALVE_DHW if name == "dhw" else VALVE_BUFFER
                break
        start = next((result.plans[k].steps[i].start for k in order if i < len(result.plans[k].steps)), None)
        if start is not None:
            result.valve.append((start, position))
    return result
