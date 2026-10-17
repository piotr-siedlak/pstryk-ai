"""Strategy "boost only": the heat pump runs on its own, we only boost in cheap hours.

The heat pump keeps its own logic (thermostat / weather curve) and holds its
setpoint (``cfg.target_t``). Pstryk AI only says *"now run at 100 % up to the
boost temperature"* in hours where that heat is cheaper than the heat the pump
would otherwise produce on its own later. Comfort is the heat pump's job, so
there is no comfort risk: without a boost the storage never drops below the
heat pump's setpoint (as modelled), it simply is not pre-charged.

Model per hour (same physics as :mod:`thermal_storage`):

* auto: the pump delivers what is needed to hold the setpoint
  (``q = clip((setpoint − T)·C + demand + losses, 0, P_max)``),
* boost: the pump runs at 100 % until the boost temperature; an optional
  heater stage can be added (e.g. at negative prices).

A dynamic program over the storage temperature chooses the boost hours. Heat
stored above the setpoint is valued at the average cost of the pump's own
heating later (that is what it displaces). Boosts are only considered in
candidate hours: the cheapest ``boost_percentile`` of the next 24 hours, or
any hour with a negative price.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import datetime, timedelta
import math

from ..models.optimizer import BufferPlan, BufferStep
from ..models.price_slot import PriceSlot, iso
from .heat_pump import CopModel
from .thermal_storage import (
    GRID_K,
    SUPPLY_DELTA,
    BufferConfig,
    _fallback,
    _Hour,
    _local_hhmm,
    _prepare_hours,
    _step2,
    storage_soc,
)

BOOST_START_PENALTY = 0.1  # PLN – avoids pointless 1-hour flip-flops


def _auto_level(cfg: BufferConfig, t: float, h: _Hour) -> float:
    """Power fraction the heat pump uses on its own to hold its setpoint."""
    if not cfg.hp_enabled or cfg.hp_thermal_kw <= 0:
        return 0.0
    loss = cfg.loss_kw_per_k * max(0.0, t - 20.0)
    need = (cfg.target_t - t) * cfg.capacity + h.demand + loss
    return max(0.0, min(1.0, need / cfg.hp_thermal_kw))


def _candidates(hours: Sequence[_Hour], percentile: float) -> list[bool]:
    out = []
    for i, h in enumerate(hours):
        window = sorted(x.buy for x in hours[i : i + 24])
        k = max(0, min(len(window) - 1, math.ceil(len(window) * percentile) - 1))
        out.append(h.buy < 0 or h.buy <= window[k] + 1e-9)
    return out


def plan_boost(
    cfg: BufferConfig,
    cop: CopModel,
    *,
    now: datetime,
    current_t: float,
    slots: Sequence[PriceSlot],
    outdoor_forecast: Mapping[datetime, float],
    boost_t: float,
    boost_percentile: float = 0.4,
    default_outdoor: float = 5.0,
    advisory: bool = True,
    stale: bool = False,
    hp_available: Sequence[bool] | None = None,
    cap_kw: Sequence[float | None] | None = None,
    sell_prices: Mapping[datetime, float] | None = None,
    surplus_kwh: Mapping[datetime, float] | None = None,
) -> BufferPlan:
    hour = now.replace(minute=0, second=0, microsecond=0)
    usable: list[PriceSlot] = []
    for s in slots:
        if s.start < hour:
            continue
        if s.value is None or (usable and usable[-1].end != s.start):
            break
        usable.append(s)
        if len(usable) >= cfg.max_horizon_h:
            break
    valid_until = now + timedelta(hours=1, minutes=15)
    if stale or not usable:
        plan = _fallback(
            cfg,
            now,
            valid_until,
            "Dane nieaktualne – pompa pracuje samodzielnie" if stale else "Brak cen – pompa pracuje samodzielnie",
        )
        plan.strategy = "boost"
        return plan

    hours = _prepare_hours(
        cfg,
        usable,
        outdoor_forecast,
        default_outdoor,
        hp_available=None,
        cap_kw=cap_kw,
        sell_prices=sell_prices,
        surplus_kwh=surplus_kwh,
    )
    n = len(hours)
    boost_t = max(cfg.target_t + 1.0, min(boost_t, cfg.max_t, cfg.hp_max_t or cfg.max_t))
    boost_cfg = replace(
        cfg,
        hp_max_t=boost_t,
        heater=replace(cfg.heater, max_t=min(cfg.heater.max_t or cfg.max_t, max(boost_t, cfg.heater.max_t or boost_t)))
        if cfg.heater is not None
        else None,
    )
    stages = cfg.heater.stages if cfg.heater is not None else [0.0]
    cand = _candidates(hours, boost_percentile)
    hp_free = [True] * n if hp_available is None else [i < len(hp_available) and hp_available[i] for i in range(n)]
    strat = max(0.0, min(cfg.stratification_k, 8.0))
    heat_value = sum(h.buy / max(1.0, cop.cop(h.t_out, cfg.target_t - strat + SUPPLY_DELTA)) for h in hours) / n

    def step(t: float, boost: bool, stage: float, h: _Hour):
        if boost:
            return _step2(boost_cfg, cop, t, 1.0, stage, h)
        return _step2(boost_cfg, cop, t, _auto_level(cfg, t, h), stage, h)

    lo = min(cfg.target_t - 10.0, current_t)
    hi = max(cfg.max_t, current_t)
    grid_n = math.ceil((hi - lo) / GRID_K) + 1

    def idx(t: float) -> int:
        return max(0, min(grid_n - 1, round((t - lo) / GRID_K)))

    # state: (temp idx, boosting-last-hour) -> (cost, exact temperature)
    layer: dict[tuple[int, int], tuple[float, float]] = {(idx(current_t), 0): (0.0, current_t)}
    backs: list[dict[tuple[int, int], tuple[tuple[int, int], tuple[bool, float]]]] = []
    for i, h in enumerate(hours):
        nxt: dict[tuple[int, int], tuple[float, float]] = {}
        back: dict[tuple[int, int], tuple[tuple[int, int], tuple[bool, float]]] = {}
        options: list[tuple[bool, float]] = [(False, 0.0)]
        if cand[i]:
            if cfg.hp_enabled and hp_free[i]:
                options += [(True, st) for st in stages]
            options += [(False, st) for st in stages if st > 0]
        for state, (cost, t) in layer.items():
            for boost, stage in options:
                r = step(t, boost, stage, h)
                if (boost or stage > 0) and h.cap_kw is not None and r.e_hp + r.e_heater > h.cap_kw + 1e-6:
                    continue
                if boost and r.t_next <= step(t, False, 0.0, h).t_next + 0.05:
                    continue  # boosting would not add heat (already at boost temperature)
                c = cost + r.cost
                if (boost or stage > 0) and not state[1]:
                    c += BOOST_START_PENALTY
                key = (idx(r.t_next), 1 if (boost or stage > 0) else 0)
                if key not in nxt or c < nxt[key][0]:
                    nxt[key] = (c, r.t_next)
                    back[key] = (state, (boost, stage))
        backs.append(back)
        layer = nxt

    def terminal(v: tuple[float, float]) -> float:
        cost, t_end = v
        return cost - max(0.0, t_end - cfg.target_t) * cfg.capacity * heat_value

    final = min(layer.items(), key=lambda kv: terminal(kv[1]))[0]
    actions: list[tuple[bool, float]] = [(False, 0.0)] * n
    state = final
    for i in range(n - 1, -1, -1):
        prev, act = backs[i][state]
        actions[i] = act
        state = prev

    steps, cost, auto_cost, t_auto_end = _simulate(cfg, boost_cfg, cop, current_t, actions, usable, hours)
    savings = auto_cost - cost + (steps[-1].temperature_end - t_auto_end) * cfg.capacity * heat_value
    boosting = [i for i, a in enumerate(actions) if a[0] or a[1] > 0]
    first_start = first_stop = None
    target = boost_t
    if boosting:
        i0 = boosting[0]
        first_start = steps[i0].start
        j = i0
        while j + 1 < n and (actions[j + 1][0] or actions[j + 1][1] > 0):
            j += 1
        first_stop = steps[j].start + timedelta(hours=1)
        target = round(min(boost_t, steps[j].temperature_end + strat) * 2) / 2
    boost_now = bool(actions[0][0])
    heater_now = steps[0].heater_kw
    reason = _reason(hours, actions, steps, usable, boost_now, heater_now, boost_t, first_start)
    plan = BufferPlan(
        generated_at=now,
        valid_until=valid_until,
        should_heat=boost_now,
        target_temperature=target if boosting else cfg.target_t,
        recommended_start=first_start,
        recommended_stop=first_stop,
        recommended_duration_h=(first_stop - first_start).total_seconds() / 3600 if first_start and first_stop else 0.0,
        expected_energy_kwh=sum(s.electric_kwh for s in steps[:24]),
        expected_cost_pln=sum(s.cost for s in steps[:24]),
        expected_savings_pln=savings,
        next_heating_window={"start": iso(first_start), "end": iso(first_stop)} if first_start and first_stop else None,
        thermal_energy_target_kwh=max(0.0, (target - current_t) * cfg.capacity) if boosting else 0.0,
        optimization_confidence=1.0,
        optimization_reason=reason,
        mode="advisory" if advisory else "control",
        feasible=True,
        steps=steps,
    )
    plan.name = cfg.name
    plan.strategy = "boost"
    plan.boost_target_t = boost_t
    plan.heater_should_run = heater_now > 0
    plan.heater_power_kw = heater_now
    heater_hours = [s for s in steps if s.heater_kw > 0]
    plan.heater_next_start = heater_hours[0].start if heater_hours else None
    plan.hp_hours = [steps[i].start for i in boosting if actions[i][0]]
    plan.hp_modulation_pct = 100 if boost_now else 0
    plan.soc_pct = storage_soc(cfg, current_t)
    plan.stored_energy_kwh = max(0.0, (current_t - cfg.min_t) * cfg.capacity)
    plan.fuel_cost_pln = sum(s.fuel_cost for s in steps[:24])
    plan.boost_hours = [steps[i].start for i in boosting]
    return plan


def _simulate(cfg, boost_cfg, cop, t0, actions, usable, hours):
    """Plan trajectory and the pure-auto reference (heat pump alone)."""
    steps: list[BufferStep] = []
    t = t0
    total = 0.0
    for (boost, stage), slot, h in zip(actions, usable, hours, strict=True):
        level = 1.0 if boost else _auto_level(cfg, t, h)
        r = _step2(boost_cfg, cop, t, level, stage, h)
        total += r.cost
        steps.append(
            BufferStep(
                slot.start,
                1.0 if boost else 0.0,
                t,
                r.t_next,
                r.e_hp + r.e_heater,
                r.q_hp + r.q_heater,
                h.buy,
                r.cop,
                r.cost,
                slot.source.value,
                heater_kw=r.q_heater,
                hp_kwh=r.q_hp,
                fuel_cost=r.fuel_cost,
            )
        )
        t = r.t_next
    ta = t0
    auto = 0.0
    for h in hours:
        r = _step2(cfg, cop, ta, _auto_level(cfg, ta, h), 0.0, h)
        auto += r.cost
        ta = r.t_next
    return steps, total, auto, ta


def _reason(hours, actions, steps, usable, boost_now, heater_now, boost_t, first_start) -> str:
    if boost_now or heater_now > 0:
        what = "pompa 100%" if boost_now else ""
        if heater_now > 0:
            what = f"{what} + grzałka {heater_now:.1f} kW" if what else f"grzałka {heater_now:.1f} kW"
        price = hours[0].buy
        later = [h.buy for h in hours[1:24]]
        avg_later = sum(later) / len(later) if later else price
        return (
            f"Doładowanie teraz – tania energia ({price:.3f} zł/kWh, później śr. {avg_later:.3f}); "
            f"{what} do {boost_t:.0f} °C, potem pompa pracuje samodzielnie"
        )
    if first_start is not None:
        return f"Pompa pracuje samodzielnie – doładowanie od {_local_hhmm(first_start)}"
    return "Pompa pracuje samodzielnie – doładowanie się nie opłaca w horyzoncie"


def auto_only_cost(cfg: BufferConfig, cop: CopModel, t0: float, hours: Sequence[_Hour]) -> float:
    ta = t0
    total = 0.0
    for h in hours:
        r = _step2(cfg, cop, ta, _auto_level(cfg, ta, h), 0.0, h)
        total += r.cost
        ta = r.t_next
    return total
