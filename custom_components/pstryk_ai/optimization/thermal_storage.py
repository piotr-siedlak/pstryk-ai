"""Thermal buffer optimiser (model-predictive, dynamic programming).

State: buffer temperature on a 0.5 K grid + compressor run/off counters.
Each hour the heat pump is either off or on at nominal thermal power (the
on-hour is truncated when the buffer would exceed its maximum temperature).

Energy balance per hour (kWh_th):

    C · ΔT = Q_hp − Q_demand(T_out) − U_loss · (T_buffer − T_room)
    C      = volume_l · 0.001163 kWh/(l·K)

Electricity = Q_hp / COP(T_out, T_supply ≈ T_buffer + 5 K).

The objective is electricity cost (risk-adjusted price for forecast slots)
plus a comfort penalty below the minimum temperature and a small start
penalty, minus the value of heat left in the buffer at the end of the
horizon. The plan is re-optimised every hour (receding horizon) and whenever
the measured temperature deviates from the plan.

SAFETY: this module only produces advice. Hardware thermostats, over-
temperature protection and manufacturer limits are never bypassed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
import math

from ..models.optimizer import BufferPlan, BufferStep
from ..models.price_slot import PriceSlot, iso
from .cheapest_hours import effective_price
from .heat_pump import CopModel

WATER_KWH_PER_L_K = 0.001163
GRID_K = 0.5
ROOM_T = 20.0
SUPPLY_DELTA = 5.0


def thermal_capacity_kwh_per_k(volume_l: float) -> float:
    return volume_l * WATER_KWH_PER_L_K


def thermal_energy_kwh(volume_l: float, delta_k: float) -> float:
    return volume_l * WATER_KWH_PER_L_K * delta_k


@dataclass(slots=True)
class BufferConfig:
    volume_l: float = 500.0
    min_t: float = 30.0
    max_t: float = 55.0
    target_t: float = 40.0
    hp_thermal_kw: float = 9.0
    hp_electric_kw: float = 3.0
    loss_kw_per_k: float = 0.003  # storage standby losses
    building_kw_per_k: float = 0.25  # building heat demand per K below base temp
    base_t: float = 18.0
    min_runtime_h: int = 1
    min_offtime_h: int = 1
    max_starts_per_day: int = 6
    comfort_penalty_pln_per_kh: float = 5.0
    start_penalty_pln: float = 0.2
    risk_aversion: float = 0.3
    max_horizon_h: int = 72

    @property
    def capacity(self) -> float:
        return thermal_capacity_kwh_per_k(self.volume_l)


def heat_demand_kw(cfg: BufferConfig, t_out: float) -> float:
    return cfg.building_kw_per_k * max(0.0, cfg.base_t - t_out)


def _step(cfg: BufferConfig, cop: CopModel, t: float, on: bool, t_out: float) -> tuple[float, float, float, float]:
    """Return (t_next, q_hp_kwh, electric_kwh, cop) for one hour."""
    cap = cfg.capacity
    demand = heat_demand_kw(cfg, t_out)
    loss = cfg.loss_kw_per_k * max(0.0, t - ROOM_T)
    q_hp = 0.0
    if on:
        headroom = (cfg.max_t - t) * cap + demand + loss
        q_hp = max(0.0, min(cfg.hp_thermal_kw, headroom))
    t_next = t + (q_hp - demand - loss) / cap
    c = cop.cop(t_out, (t + t_next) / 2 + SUPPLY_DELTA)
    electric = q_hp / c if q_hp > 0 else 0.0
    if cfg.hp_electric_kw > 0:
        electric = min(electric, cfg.hp_electric_kw * 1.5)
    return t_next, q_hp, electric, c


def simulate(
    cfg: BufferConfig,
    cop: CopModel,
    t0: float,
    actions: Sequence[bool],
    slots: Sequence[PriceSlot],
    outdoor: Sequence[float],
) -> tuple[list[BufferStep], float]:
    steps: list[BufferStep] = []
    t = t0
    total = 0.0
    for on, slot, t_out in zip(actions, slots, outdoor, strict=False):
        t_next, q, e, c = _step(cfg, cop, t, on, t_out)
        price = slot.value or 0.0
        cost = e * price
        total += cost
        steps.append(BufferStep(slot.start, 1.0 if q > 0 else 0.0, t, t_next, e, q, price, c, cost, slot.source.value))
        t = t_next
    return steps, total


def _thermostat_actions(cfg: BufferConfig, cop: CopModel, t0: float, outdoor: Sequence[float], n: int) -> list[bool]:
    """Non-optimised reference: hysteresis around the target temperature."""
    actions = []
    t = t0
    on = t < cfg.target_t - 2
    for i in range(n):
        if t <= cfg.target_t - 2:
            on = True
        elif t >= cfg.target_t:
            on = False
        actions.append(on)
        t, *_ = _step(cfg, cop, t, on, outdoor[i])
    return actions


def plan_buffer(
    cfg: BufferConfig,
    cop: CopModel,
    *,
    now: datetime,
    current_t: float,
    slots: Sequence[PriceSlot],
    outdoor_forecast: Mapping[datetime, float],
    default_outdoor: float = 5.0,
    advisory: bool = True,
    stale: bool = False,
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
        reason = (
            "Dane nieaktualne – sterowanie lokalne (termostat Loxone)" if stale else "Brak cen – sterowanie lokalne"
        )
        return BufferPlan(
            generated_at=now,
            valid_until=valid_until,
            should_heat=False,
            target_temperature=cfg.target_t,
            recommended_start=None,
            recommended_stop=None,
            recommended_duration_h=0.0,
            expected_energy_kwh=0.0,
            expected_cost_pln=0.0,
            expected_savings_pln=0.0,
            next_heating_window=None,
            thermal_energy_target_kwh=0.0,
            optimization_confidence=0.0,
            optimization_reason=reason,
            mode="fallback",
            feasible=False,
        )

    outdoor = [outdoor_forecast.get(s.start, default_outdoor) for s in usable]
    prices = [effective_price(s, cfg.risk_aversion) or 0.0 for s in usable]
    n = len(usable)

    lo = min(cfg.min_t - 5.0, current_t)
    hi = cfg.max_t
    grid_n = math.ceil((hi - lo) / GRID_K) + 1

    def idx(t: float) -> int:
        return max(0, min(grid_n - 1, round((t - lo) / GRID_K)))

    min_run = max(1, cfg.min_runtime_h)
    min_off = max(0, cfg.min_offtime_h)
    # terminal value of stored heat (PLN per kWh_th), from average future cost
    avg_cop = sum(cop.cop(o, cfg.target_t + SUPPLY_DELTA) for o in outdoor) / n
    heat_value = (sum(prices) / n) / max(avg_cop, 1.0)

    # DP: state (temp_idx, mode, length) -> (cost, exact temperature).
    # The exact temperature of the cheapest path is carried along so that slow
    # cooling (< grid step per hour) is not rounded away.
    State = tuple[int, int, int]
    layer: dict[State, tuple[float, float]] = {(idx(current_t), 0, min_off): (0.0, current_t)}
    backs: list[dict[State, tuple[State, bool]]] = []
    for i in range(n):
        nxt: dict[State, tuple[float, float]] = {}
        back: dict[State, tuple[State, bool]] = {}
        for state, (cost, t) in layer.items():
            _, mode, length = state
            for on in (False, True):
                if on and mode == 0 and length < min_off:
                    continue
                if not on and mode == 1 and length < min_run:
                    continue
                t_next, _, e, _ = _step(cfg, cop, t, on, outdoor[i])
                c = cost + e * prices[i]
                if t_next < cfg.min_t:
                    c += (cfg.min_t - t_next) * cfg.comfort_penalty_pln_per_kh
                if on and mode == 0:
                    c += cfg.start_penalty_pln
                if on:
                    key = (idx(t_next), 1, min(min_run, length + 1) if mode == 1 else 1)
                else:
                    key = (idx(t_next), 0, min(min_off, length + 1) if mode == 0 else (1 if min_off else 0))
                if key not in nxt or c < nxt[key][0]:
                    nxt[key] = (c, t_next)
                    back[key] = (state, on)
        backs.append(back)
        layer = nxt

    def terminal(value: tuple[float, float]) -> float:
        cost, t_end = value
        stored = max(0.0, t_end - cfg.min_t) * cfg.capacity
        return cost - stored * heat_value

    final = min(layer.items(), key=lambda kv: terminal(kv[1]))[0]
    actions: list[bool] = [False] * n
    state = final
    for i in range(n - 1, -1, -1):
        prev, on = backs[i][state]
        actions[i] = on
        state = prev

    steps, cost = simulate(cfg, cop, current_t, actions, usable, outdoor)
    ref_actions = _thermostat_actions(cfg, cop, current_t, outdoor, n)
    ref_steps, ref_cost = simulate(cfg, cop, current_t, ref_actions, usable, outdoor)
    # correct for different end-of-horizon heat content
    delta_heat = (steps[-1].temperature_end - ref_steps[-1].temperature_end) * cfg.capacity
    savings = ref_cost - cost + delta_heat * heat_value

    heating = [s for s in steps if s.thermal_kwh > 0]
    first_start = first_stop = None
    target_temperature = cfg.target_t
    if heating:
        first_start = heating[0].start
        first_stop = first_start
        peak = heating[0].temperature_end
        for s in steps[steps.index(heating[0]) :]:
            if s.thermal_kwh <= 0:
                break
            first_stop = s.start + timedelta(hours=1)
            peak = s.temperature_end
        target_temperature = round(min(cfg.max_t, max(cfg.min_t, peak)) * 2) / 2
    duration = (first_stop - first_start).total_seconds() / 3600 if first_start and first_stop else 0.0

    conf_values = [
        (1.0 if s.source == "ACTUAL_PSTRYK" else (sl.confidence if sl.confidence is not None else 0.7))
        for s, sl in zip(steps, usable, strict=False)
        if s.thermal_kwh > 0
    ]
    confidence = sum(conf_values) / len(conf_values) if conf_values else 1.0
    starts = sum(1 for i, a in enumerate(actions[:24]) if a and (i == 0 or not actions[i - 1]))
    should_heat = bool(actions[0] and steps[0].thermal_kwh > 0)
    min_temp = min(s.temperature_end for s in steps)
    if should_heat:
        reason = "Grzanie teraz – najniższy koszt ciepła w horyzoncie"
    elif heating:
        reason = f"Czekaj – tańsze ciepło od {iso(first_start)}"
    else:
        reason = "Bufor wystarczający – grzanie niepotrzebne w horyzoncie"
    if min_temp < cfg.min_t:
        reason += "; uwaga: prognozowany spadek poniżej minimum"
    if starts > cfg.max_starts_per_day:
        reason += f"; liczba startów {starts} > {cfg.max_starts_per_day}"

    return BufferPlan(
        generated_at=now,
        valid_until=valid_until,
        should_heat=should_heat,
        target_temperature=target_temperature,
        recommended_start=first_start,
        recommended_stop=first_stop,
        recommended_duration_h=duration,
        expected_energy_kwh=sum(s.electric_kwh for s in steps[:24]),
        expected_cost_pln=sum(s.cost for s in steps[:24]),
        expected_savings_pln=max(-1e6, savings),
        next_heating_window=(
            {"start": iso(first_start), "end": iso(first_stop)} if first_start and first_stop else None
        ),
        thermal_energy_target_kwh=max(0.0, (target_temperature - current_t) * cfg.capacity),
        optimization_confidence=confidence,
        optimization_reason=reason,
        mode="advisory" if advisory else "control",
        feasible=min_temp >= cfg.min_t - 0.5,
        steps=steps,
    )
