"""Thermal storage optimiser (model-predictive, dynamic programming).

Used for the heating buffer and for the domestic hot-water tank (CWU). One
model, different configuration:

* State: mean storage temperature on a 0.5 K grid (the exact temperature of the
  cheapest path is carried along) + heat-pump run/off counters + an optional
  "legionella reached" flag.
* Actions per hour: heat pump on/off (if allowed in that hour – a shared heat
  pump with a switching valve can serve only one storage at a time) and an
  auxiliary heater stage (electric or gas, several power steps).

Energy balance per hour (kWh_th):

    C · ΔT = Q_hp + Q_heater − Q_demand − U_loss · (T − T_room)
    C      = volume_l · 0.001163 kWh/(l·K)

* Heat pump electricity = Q_hp / COP(T_out, T_supply); the heat pump cannot heat
  above ``hp_max_t``. Heat-pump physics (v0.6):

  - **capacity falls in frost**: output at −15 °C from the options, otherwise a
    generic −1.2 %/K below +7 °C (typical air/water datasheets);
  - **part load**: the condenser lift scales with power – T_supply = bottom
    layer + 5 K × power fraction – so an inverter is more efficient at 30 %;
  - **cycling** below the minimum modulation (on/off in the hour) loses
    efficiency per EN 14825: COP × CR / (Cc·CR + 1 − Cc), Cc = 0.9;
  - optional **heating curve**: the heat pump's setpoint and the comfort
    minimum follow the outdoor temperature (``curve_slope`` K per K below 0 °C).
* Electric heater electricity = Q_heater / efficiency; gas heater fuel cost =
  Q_heater / efficiency · fuel_price.
* Electricity cost uses the (risk-adjusted) buy price; with PV surplus the first
  ``surplus`` kWh of the hour are valued at the sell price (self-consumption).
* Optional per-hour electric power cap (connection limit minus other loads).

Penalties: below minimum temperature (comfort), below a "ready by" temperature
at a given time (e.g. hot water at 06:00), missing the legionella temperature
before its deadline, compressor starts. A terminal value rewards heat left in
the storage. Top/bottom sensors are used for the current state: mean = (top +
bottom) / 2, and the comfort check uses the top layer (mean + stratification).

SAFETY: advice only. Hardware thermostats, over-temperature protection and
manufacturer limits are never bypassed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
import math
from zoneinfo import ZoneInfo

from ..const import LOCAL_TZ
from ..models.optimizer import BufferPlan, BufferStep
from ..models.price_slot import PriceSlot, iso
from .cheapest_hours import effective_price
from .heat_pump import CopModel

WATER_KWH_PER_L_K = 0.001163
GRID_K = 0.5
ROOM_T = 20.0
SUPPLY_DELTA = 5.0
HEATER_USE_PENALTY = 0.005  # PLN per kWh_th – prefers the heat pump when costs are equal
CYCLING_CC = 0.9  # EN 14825 degradation coefficient (air/water) for on/off cycling
DERATE_PER_K = 0.012  # generic capacity loss per K below +7 °C
DERATE_REF_T = 7.0
MIN_CAPACITY_SHARE = 0.4
CURVE_REF_T = 0.0  # the configured target/minimum apply at this outdoor temperature


def thermal_capacity_kwh_per_k(volume_l: float) -> float:
    return volume_l * WATER_KWH_PER_L_K


def thermal_energy_kwh(volume_l: float, delta_k: float) -> float:
    return volume_l * WATER_KWH_PER_L_K * delta_k


@dataclass(slots=True)
class HeaterConfig:
    """Auxiliary heater of a storage (electric element or gas boiler)."""

    kind: str = "electric"  # electric | gas
    steps_kw: list[float] = field(default_factory=lambda: [3.0])  # heat output per stage
    efficiency: float = 1.0
    fuel_price: float = 0.35  # PLN per kWh of fuel (gas)
    max_t: float | None = None  # None = storage max_t

    @property
    def stages(self) -> list[float]:
        return [0.0, *sorted(s for s in self.steps_kw if s > 0)]

    @property
    def is_electric(self) -> bool:
        return self.kind != "gas"


@dataclass(slots=True)
class ReadyConstraint:
    """Storage must have at least ``min_t`` (top layer) at ``at``."""

    at: datetime
    min_t: float


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
    comfort_penalty_pln_per_kh: float = 30.0  # near-hard: below minimum is almost never worth it
    start_penalty_pln: float = 0.2
    risk_aversion: float = 0.3
    max_horizon_h: int = 72
    # --- generalisation (v0.4)
    name: str = "buffer"
    hp_enabled: bool = True
    hp_max_t: float | None = None  # heat pump supply limit (None = max_t)
    heater: HeaterConfig | None = None
    demand_kw: Sequence[float] | None = None  # per-hour demand override (e.g. hot-water draw)
    ready: list[ReadyConstraint] = field(default_factory=list)
    ready_penalty_pln_per_k: float = 20.0
    legionella_t: float | None = None
    legionella_deadline_h: int = 24
    legionella_penalty_pln: float = 30.0
    stratification_k: float = 0.0  # (top − bottom) / 2 measured now; top ≈ mean + this
    hp_levels: tuple[float, ...] = (1.0,)  # heat-pump power levels (fractions); (0.3, 0.65, 1.0) = inverter
    # --- heat-pump physics (v0.6)
    hp_kw_at_minus15: float | None = None  # heat output at −15 °C (None = generic derating)
    curve_slope: float = 0.0  # heating curve: setpoint/minimum + slope · (0 °C − T_out); 0 = fixed

    @property
    def capacity(self) -> float:
        return thermal_capacity_kwh_per_k(self.volume_l)

    @property
    def min_level(self) -> float:
        """Lowest continuous heat-pump power fraction (below it the compressor cycles)."""
        return max(0.05, min(1.0, min(self.hp_levels))) if self.hp_levels else 1.0


def hp_capacity_kw(cfg: BufferConfig, t_out: float) -> float:
    """Maximum heat output of the heat pump at this outdoor temperature."""
    nominal = cfg.hp_thermal_kw
    if t_out >= DERATE_REF_T or nominal <= 0:
        return nominal
    if cfg.hp_kw_at_minus15 is not None and cfg.hp_kw_at_minus15 > 0:
        slope = (nominal - cfg.hp_kw_at_minus15) / (DERATE_REF_T + 15.0)
        value = nominal - slope * (DERATE_REF_T - t_out)
    else:
        value = nominal * (1.0 - DERATE_PER_K * (DERATE_REF_T - t_out))
    return max(MIN_CAPACITY_SHARE * nominal, min(nominal, value))


def min_at(cfg: BufferConfig, t_out: float) -> float:
    """Comfort minimum (top layer) at this outdoor temperature (heating curve)."""
    if not cfg.curve_slope:
        return cfg.min_t
    return max(ROOM_T + 2.0, min(cfg.max_t - 2.0, cfg.min_t + cfg.curve_slope * (CURVE_REF_T - t_out)))


def setpoint_at(cfg: BufferConfig, t_out: float) -> float:
    """The heat pump's own setpoint at this outdoor temperature (heating curve)."""
    value = cfg.target_t + cfg.curve_slope * (CURVE_REF_T - t_out) if cfg.curve_slope else cfg.target_t
    hi = min(cfg.max_t, cfg.hp_max_t if cfg.hp_max_t is not None else cfg.max_t)
    return max(min_at(cfg, t_out) + 1.0, min(hi, value))


def part_load_factor(ratio: float) -> float:
    """EN 14825 cycling loss: COP multiplier at capacity ratio ``ratio`` (0–1)."""
    cr = max(0.02, min(1.0, ratio))
    return cr / (CYCLING_CC * cr + 1.0 - CYCLING_CC)


def _local_hhmm(moment: datetime | None) -> str:
    if moment is None:
        return "–"
    return moment.astimezone(ZoneInfo(LOCAL_TZ)).strftime("%H:%M")


def heat_demand_kw(cfg: BufferConfig, t_out: float) -> float:
    return cfg.building_kw_per_k * max(0.0, cfg.base_t - t_out)


@dataclass(slots=True)
class _Hour:
    """Per-hour inputs prepared once for the DP."""

    t_out: float
    demand: float
    buy: float
    sell: float
    surplus_kwh: float
    hp_available: bool
    cap_kw: float | None
    ready_t: float | None


@dataclass(slots=True)
class _StepResult:
    t_next: float
    q_hp: float
    q_heater: float
    e_hp: float
    e_heater: float
    fuel_cost: float
    cop: float
    cost: float


def _elec_cost(h: _Hour, kwh: float) -> float:
    if kwh <= 0:
        return 0.0
    own = min(kwh, h.surplus_kwh)
    return own * h.sell + (kwh - own) * h.buy


def _step2(cfg: BufferConfig, cop: CopModel, t: float, hp_on: bool | float, heater_kw: float, h: _Hour) -> _StepResult:
    cap = cfg.capacity
    loss = cfg.loss_kw_per_k * max(0.0, t - ROOM_T)
    need = h.demand + loss
    q_hp = 0.0
    hp_limit = cfg.hp_max_t if cfg.hp_max_t is not None else cfg.max_t
    hp_limit = min(hp_limit, cfg.max_t)
    level = float(hp_on)
    cap_hp = hp_capacity_kw(cfg, h.t_out)
    if level > 0:
        # may still cover losses/demand at the limit (keeps the run going)
        q_hp = max(0.0, min(cap_hp * level, (hp_limit - t) * cap + need))
    q_heat = 0.0
    if heater_kw > 0 and cfg.heater is not None:
        h_limit = min(cfg.heater.max_t if cfg.heater.max_t is not None else cfg.max_t, cfg.max_t)
        q_heat = max(0.0, min(heater_kw, (h_limit - t) * cap + need - q_hp))
    t_next = t + (q_hp + q_heat - need) / cap
    # the heat pump heats the (colder) bottom water: supply ≈ bottom layer + ΔT
    bottom = (t + t_next) / 2 - max(0.0, min(cfg.stratification_k, 8.0))
    if q_hp > 0 and cap_hp > 0:
        ratio = q_hp / cap_hp
        min_level = cfg.min_level
        run = max(ratio, min_level)  # below the minimum the compressor runs at it, on/off
        c = cop.cop(h.t_out, bottom + SUPPLY_DELTA * run)
        if ratio < min_level - 1e-9:
            c = max(cop.min_cop, c * part_load_factor(ratio / min_level))
    else:
        c = cop.cop(h.t_out, bottom + SUPPLY_DELTA)
    e_hp = q_hp / c if q_hp > 0 else 0.0
    if cfg.hp_electric_kw > 0:
        e_hp = min(e_hp, cfg.hp_electric_kw * 1.5 * max(level, 0.0))
    e_heat = 0.0
    fuel = 0.0
    if q_heat > 0 and cfg.heater is not None:
        eff = max(0.05, cfg.heater.efficiency)
        if cfg.heater.is_electric:
            e_heat = q_heat / eff
        else:
            fuel = q_heat / eff * cfg.heater.fuel_price
    cost = _elec_cost(h, e_hp + e_heat) + fuel
    return _StepResult(t_next, q_hp, q_heat, e_hp, e_heat, fuel, c, cost)


# Backwards-compatible single-source step (used by older callers/tests)
def _step(cfg: BufferConfig, cop: CopModel, t: float, on: bool, t_out: float) -> tuple[float, float, float, float]:
    h = _Hour(t_out, heat_demand_kw(cfg, t_out), 0.0, 0.0, 0.0, True, None, None)
    r = _step2(cfg, cop, t, on, 0.0, h)
    return r.t_next, r.q_hp, r.e_hp, r.cop


def _prepare_hours(
    cfg: BufferConfig,
    usable: Sequence[PriceSlot],
    outdoor_forecast: Mapping[datetime, float],
    default_outdoor: float,
    *,
    hp_available: Sequence[bool] | None,
    cap_kw: Sequence[float | None] | None,
    sell_prices: Mapping[datetime, float] | None,
    surplus_kwh: Mapping[datetime, float] | None,
) -> list[_Hour]:
    hours: list[_Hour] = []
    for i, s in enumerate(usable):
        t_out = outdoor_forecast.get(s.start, default_outdoor)
        demand = (
            cfg.demand_kw[i] if cfg.demand_kw is not None and i < len(cfg.demand_kw) else heat_demand_kw(cfg, t_out)
        )
        ready_t = None
        for r in cfg.ready:
            if s.start < r.at <= s.end:
                ready_t = max(ready_t or r.min_t, r.min_t)
        hours.append(
            _Hour(
                t_out=t_out,
                demand=max(0.0, demand),
                buy=effective_price(s, cfg.risk_aversion) or 0.0,
                sell=(sell_prices or {}).get(s.start, 0.0),
                surplus_kwh=max(0.0, (surplus_kwh or {}).get(s.start, 0.0)),
                hp_available=cfg.hp_enabled and (hp_available is None or (i < len(hp_available) and hp_available[i])),
                cap_kw=None if cap_kw is None or i >= len(cap_kw) else cap_kw[i],
                ready_t=ready_t,
            )
        )
    return hours


def simulate(
    cfg: BufferConfig,
    cop: CopModel,
    t0: float,
    actions: Sequence[bool | tuple[bool, float]],
    slots: Sequence[PriceSlot],
    outdoor: Sequence[float] | Sequence[_Hour],
) -> tuple[list[BufferStep], float]:
    steps: list[BufferStep] = []
    t = t0
    total = 0.0
    for i, (action, slot) in enumerate(zip(actions, slots, strict=False)):
        hp_on, heater_kw = action if isinstance(action, tuple) else (float(bool(action)), 0.0)
        src = outdoor[i]
        h = (
            src
            if isinstance(src, _Hour)
            else _Hour(src, heat_demand_kw(cfg, src), slot.value or 0.0, 0.0, 0.0, True, None, None)
        )
        r = _step2(cfg, cop, t, hp_on, heater_kw, h)
        total += r.cost
        steps.append(
            BufferStep(
                slot.start,
                float(hp_on) if r.q_hp > 0 else 0.0,
                t,
                r.t_next,
                r.e_hp + r.e_heater,
                r.q_hp + r.q_heater,
                h.buy if isinstance(src, _Hour) else (slot.value or 0.0),
                r.cop,
                r.cost,
                slot.source.value,
                heater_kw=r.q_heater,
                hp_kwh=r.q_hp,
                fuel_cost=r.fuel_cost,
            )
        )
        t = r.t_next
    return steps, total


def _thermostat_actions(
    cfg: BufferConfig, cop: CopModel, t0: float, hours: Sequence[float] | Sequence[_Hour], n: int
) -> list[tuple[float, float]]:
    """Non-optimised reference with the SAME minimum comfort.

    An ordinary thermostat: heat when the top layer falls to min + 1 K, stop at
    min + 6 K (or the target, whichever is lower). Uses the heat pump when
    allowed – an inverter at the lowest power level that still charges, like
    its own controller would – otherwise the largest heater stage. Comparing
    with a thermostat that keeps a higher temperature or runs at full power
    would inflate the savings.
    """
    actions: list[tuple[float, float]] = []
    t = t0
    strat = max(0.0, min(cfg.stratification_k, 8.0))
    on = None
    big = cfg.heater.stages[-1] if cfg.heater is not None else 0.0
    levels = sorted({max(0.05, min(1.0, x)) for x in (cfg.hp_levels or (1.0,))})
    for i in range(n):
        src = hours[i]
        h = src if isinstance(src, _Hour) else _Hour(src, heat_demand_kw(cfg, src), 0.0, 0.0, 0.0, True, None, None)
        floor = min_at(cfg, h.t_out)
        low = floor + 1.0
        high = min(cfg.max_t, max(low + 2.0, min(setpoint_at(cfg, h.t_out), floor + 6.0)))
        if on is None:
            on = t + strat <= low
        if t + strat <= low:
            on = True
        elif t + strat >= high:
            on = False
        use_hp = on and h.hp_available and cfg.hp_enabled
        heater = big if on and not use_hp else 0.0
        level = 0.0
        if use_hp:
            level = levels[-1]
            for lv in levels:  # lowest level that still charges by ≥ 0.5 K
                if _step2(cfg, cop, t, lv, 0.0, h).t_next >= t + 0.5:
                    level = lv
                    break
        actions.append((level, heater))
        t = _step2(cfg, cop, t, level, heater, h).t_next
    return actions


def _fallback(cfg: BufferConfig, now: datetime, valid_until: datetime, reason: str) -> BufferPlan:
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
        reason = (
            "Dane nieaktualne – sterowanie lokalne (termostat Loxone)" if stale else "Brak cen – sterowanie lokalne"
        )
        return _fallback(cfg, now, valid_until, reason)

    hours = _prepare_hours(
        cfg,
        usable,
        outdoor_forecast,
        default_outdoor,
        hp_available=hp_available,
        cap_kw=cap_kw,
        sell_prices=sell_prices,
        surplus_kwh=surplus_kwh,
    )
    n = len(hours)
    strat = max(0.0, min(cfg.stratification_k, 8.0))
    mins = [min_at(cfg, h.t_out) for h in hours]

    lo = min(min(mins) - 5.0, current_t)
    hi = max(cfg.max_t, current_t)
    grid_n = math.ceil((hi - lo) / GRID_K) + 1

    def idx(t: float) -> int:
        return max(0, min(grid_n - 1, round((t - lo) / GRID_K)))

    min_run = max(1, cfg.min_runtime_h)
    min_off = max(0, cfg.min_offtime_h)
    stages = cfg.heater.stages if cfg.heater is not None else [0.0]
    # terminal value of stored heat (PLN per kWh_th): cheapest average way to make heat
    avg_buy = sum(h.buy for h in hours) / n
    candidates = []
    if cfg.hp_enabled:
        avg_cop = sum(cop.cop(h.t_out, setpoint_at(cfg, h.t_out) + SUPPLY_DELTA) for h in hours) / n
        candidates.append(avg_buy / max(avg_cop, 1.0))
    if cfg.heater is not None:
        eff = max(0.05, cfg.heater.efficiency)
        candidates.append(avg_buy / eff if cfg.heater.is_electric else cfg.heater.fuel_price / eff)
    heat_value = min(candidates) if candidates else 0.0
    leg_needed = cfg.legionella_t is not None
    leg_deadline = min(n, max(1, cfg.legionella_deadline_h))
    leg_done_at_start = 1 if (leg_needed and current_t >= (cfg.legionella_t or 0) - 0.2) else 0

    # DP: state (temp_idx, mode, length, legionella_flag) -> (cost, exact temperature)
    State = tuple[int, int, int, int]
    start_state: State = (idx(current_t), 0, min_off, leg_done_at_start)
    layer: dict[State, tuple[float, float]] = {start_state: (0.0, current_t)}
    backs: list[dict[State, tuple[State, tuple[float, float]]]] = []
    for i, h in enumerate(hours):
        nxt: dict[State, tuple[float, float]] = {}
        back: dict[State, tuple[State, tuple[float, float]]] = {}
        levels = tuple(sorted({max(0.05, min(1.0, x)) for x in (cfg.hp_levels or (1.0,))}))
        hp_options: tuple[float, ...] = (0.0, *levels) if h.hp_available else (0.0,)
        for state, (cost, t) in layer.items():
            _, mode, length, leg = state
            for on in hp_options:
                if on > 0 and mode == 0 and length < min_off:
                    continue
                if on == 0 and mode == 1 and length < min_run:
                    continue
                for stage in stages:
                    r = _step2(cfg, cop, t, on, stage, h)
                    if stage > 0 and r.q_heater <= 0:
                        continue  # heater would not add heat (at its limit)
                    if h.cap_kw is not None and r.e_hp + r.e_heater > h.cap_kw + 1e-6:
                        continue
                    c = cost + r.cost + HEATER_USE_PENALTY * r.q_heater
                    top_next = r.t_next + strat
                    if top_next < mins[i]:
                        c += (mins[i] - top_next) * cfg.comfort_penalty_pln_per_kh
                    if h.ready_t is not None and top_next < h.ready_t:
                        c += (h.ready_t - top_next) * cfg.ready_penalty_pln_per_k
                    if on > 0 and mode == 0:
                        c += cfg.start_penalty_pln
                    new_leg = leg
                    if leg_needed and not leg and i < leg_deadline and r.t_next >= (cfg.legionella_t or 0) - 0.2:
                        new_leg = 1
                    if leg_needed and not new_leg and i == leg_deadline - 1:
                        c += cfg.legionella_penalty_pln
                    if on > 0:
                        key = (idx(r.t_next), 1, min(min_run, length + 1) if mode == 1 else 1, new_leg)
                    else:
                        key = (
                            idx(r.t_next),
                            0,
                            min(min_off, length + 1) if mode == 0 else (1 if min_off else 0),
                            new_leg,
                        )
                    if key not in nxt or c < nxt[key][0]:
                        nxt[key] = (c, r.t_next)
                        back[key] = (state, (on, stage))
        backs.append(back)
        layer = nxt

    def terminal(value: tuple[float, float]) -> float:
        cost, t_end = value
        stored = max(0.0, t_end - cfg.min_t) * cfg.capacity
        return cost - stored * heat_value

    final = min(layer.items(), key=lambda kv: terminal(kv[1]))[0]
    actions: list[tuple[float, float]] = [(0.0, 0.0)] * n
    state = final
    for i in range(n - 1, -1, -1):
        prev, act = backs[i][state]
        actions[i] = act
        state = prev

    steps, cost = simulate(cfg, cop, current_t, actions, usable, hours)
    ref_actions = _thermostat_actions(cfg, cop, current_t, hours, n)
    ref_steps, ref_cost = simulate(cfg, cop, current_t, ref_actions, usable, hours)
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
        target_temperature = round(min(cfg.max_t, max(mins[0], peak + strat)) * 2) / 2
    duration = (first_stop - first_start).total_seconds() / 3600 if first_start and first_stop else 0.0

    conf_values = [
        (1.0 if s.source == "ACTUAL_PSTRYK" else (sl.confidence if sl.confidence is not None else 0.7))
        for s, sl in zip(steps, usable, strict=False)
        if s.thermal_kwh > 0
    ]
    confidence = sum(conf_values) / len(conf_values) if conf_values else 1.0
    hp_on_list = [a[0] > 0 and st.hp_kwh > 0 for a, st in zip(actions, steps, strict=True)]
    starts = sum(1 for i, a in enumerate(hp_on_list[:24]) if a and (i == 0 or not hp_on_list[i - 1]))
    should_heat = bool(hp_on_list[0])
    heater_now = steps[0].heater_kw
    heater_hours = [s for s in steps if s.heater_kw > 0]
    min_margin = min(s.temperature_end + strat - m for s, m in zip(steps, mins, strict=True))
    reason = _explain(cfg, cop, current_t, strat, hours, steps, usable, should_heat, heater_now, heating, first_start)
    if min_margin < 0:
        reason += "; uwaga: prognozowany spadek poniżej minimum"
    missed_ready = [
        h
        for h, s in zip(hours, steps, strict=True)
        if h.ready_t is not None and s.temperature_end + strat < h.ready_t - 0.5
    ]
    if missed_ready:
        reason += "; uwaga: temperatura gotowości nie zostanie osiągnięta"
    if starts > cfg.max_starts_per_day:
        reason += f"; liczba startów {starts} > {cfg.max_starts_per_day}"
    legionella_at = None
    if leg_needed:
        legionella_at = next((s.start for s in steps if s.temperature_end >= (cfg.legionella_t or 0) - 0.2), None)
        if legionella_at is None and not leg_done_at_start:
            reason += "; uwaga: cykl antylegionella nie zostanie wykonany"

    plan = BufferPlan(
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
        feasible=min_margin >= -0.5 and not missed_ready,
        steps=steps,
    )
    plan.heater_should_run = heater_now > 0
    plan.heater_power_kw = heater_now
    plan.heater_next_start = heater_hours[0].start if heater_hours else None
    plan.hp_hours = [s.start for s, on in zip(steps, hp_on_list, strict=True) if on]
    plan.legionella_at = legionella_at
    plan.name = cfg.name
    plan.soc_pct = storage_soc(cfg, current_t)
    plan.stored_energy_kwh = max(0.0, (current_t - cfg.min_t) * cfg.capacity)
    plan.fuel_cost_pln = sum(s.fuel_cost for s in steps[:24])
    plan.hp_modulation_pct = round(steps[0].heat_fraction * 100) if should_heat else 0
    return plan


def _explain(
    cfg: BufferConfig,
    cop: CopModel,
    current_t: float,
    strat: float,
    hours: Sequence[_Hour],
    steps: Sequence[BufferStep],
    usable: Sequence[PriceSlot],
    should_heat: bool,
    heater_now: float,
    heating: Sequence[BufferStep],
    first_start: datetime | None,
) -> str:
    """Say WHY – the real cause, not a generic phrase."""
    if not (should_heat or heater_now > 0):
        if heating:
            return f"Czekaj – tańsze ciepło od {_local_hhmm(first_start)}"
        return "Zapas ciepła wystarczający – grzanie niepotrzebne w horyzoncie"
    now_price = hours[0].buy
    prices = sorted(h.buy for h in hours)
    cheap_limit = prices[max(0, len(prices) // 4 - 1)]
    idle = _step2(cfg, cop, current_t, 0.0, 0.0, hours[0])
    forced = idle.t_next + strat < min_at(cfg, hours[0].t_out) + 0.2
    ready_forced = hours[0].ready_t is not None and idle.t_next + strat < hours[0].ready_t
    level = steps[0].heat_fraction
    power = f" (moc {round(level * 100)}%)" if 0 < level < 0.99 else ""
    source = "pompa ciepła" if should_heat else ""
    if heater_now > 0:
        source = f"{source} + grzałka {heater_now:.1f} kW" if source else f"grzałka {heater_now:.1f} kW"
    if forced or ready_forced:
        what = "temperatury gotowości" if ready_forced and not forced else "minimum"
        price_note = "cena wysoka – tylko tyle, ile trzeba" if now_price > cheap_limit else "cena niska"
        return (
            f"Grzanie konieczne – bez grzania spadek poniżej {what} w tej godzinie "
            f"(góra {current_t + strat:.1f} °C); {price_note}; {source}{power}"
        )
    if now_price <= cheap_limit + 1e-9:
        return f"Tania energia teraz – ładowanie ciepła na później; {source}{power}"
    later = [h.buy for h in hours[1:13]]
    dearer = [i for i, p in enumerate(later, start=1) if p > now_price * 1.03]
    if dearer:
        start = usable[dearer[0]].start
        return f"Ładowanie przed droższymi godzinami (od {_local_hhmm(start)}); {source}{power}"
    return f"Najniższy koszt ciepła w horyzoncie; {source}{power}"


def storage_soc(cfg: BufferConfig, mean_t: float) -> float:
    """State of charge in % between min and max temperature."""
    span = max(0.1, cfg.max_t - cfg.min_t)
    return max(0.0, min(100.0, (mean_t - cfg.min_t) / span * 100.0))


def mean_from_layers(top: float | None, bottom: float | None) -> tuple[float | None, float]:
    """(mean temperature, stratification half-difference) from top/bottom readings."""
    if top is None and bottom is None:
        return None, 0.0
    if bottom is None:
        return top, 0.0
    if top is None:
        return bottom, 0.0
    return (top + bottom) / 2, max(0.0, (top - bottom) / 2)
