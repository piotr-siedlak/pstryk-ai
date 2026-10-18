"""Closed-loop simulation of a week of buffer operation (MPC as in production).

Each hour the controller sees only what it would see live: prices up to the end
of today, and from 13:00 local also tomorrow's (Pstryk publication). It plans,
applies the decision for the current hour, and the "real" storage advances with
the actual outdoor temperature. Strategies:

* ``auto``  – the heat pump alone holds its setpoint (no Pstryk AI),
* ``boost`` – heat pump alone + 100 % boosts in cheap hours (``plan_boost``),
* ``full``  – full control with modulation (``plan_buffer``),
* ``optimum`` – perfect-foresight lower bound: one plan over the whole period
  with every price known in advance. No real controller can beat it; the gap
  to it ("regret") shows how much a better algorithm could still gain.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ..const import LOCAL_TZ
from ..models.price_slot import PriceSlot, PriceSource
from .boost import _auto_level, plan_boost
from .heat_pump import CopModel
from .thermal_storage import BufferConfig, _Hour, _step2, heat_demand_kw, min_at, plan_buffer

TZ = ZoneInfo(LOCAL_TZ)


@dataclass
class SimResult:
    strategy: str
    cost: float = 0.0
    electric_kwh: float = 0.0
    heat_kwh: float = 0.0
    hours_below_min: int = 0
    min_top: float = 1e9
    hp_starts: int = 0
    boost_hours: int = 0
    end_t: float = 0.0
    trace: list[dict[str, Any]] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "cost_pln": round(self.cost, 2),
            "electric_kwh": round(self.electric_kwh, 1),
            "heat_kwh": round(self.heat_kwh, 1),
            "avg_cost_per_kwh_heat": round(self.cost / self.heat_kwh, 4) if self.heat_kwh else None,
            "hours_below_min": self.hours_below_min,
            "min_top_t": round(self.min_top, 1),
            "hp_starts": self.hp_starts,
            "boost_hours": self.boost_hours,
            "end_t": round(self.end_t, 1),
        }


def _known_until(now: datetime, last: datetime) -> datetime:
    local = now.astimezone(TZ)
    day = local.date() + timedelta(days=1 if local.hour >= 13 else 0)
    end = datetime(day.year, day.month, day.day, tzinfo=TZ) + timedelta(days=1)
    return min(end, last)


def simulate(
    strategy: str,
    prices: Sequence[tuple[datetime, float]],
    outdoor: dict[datetime, float],
    cfg: BufferConfig,
    cop: CopModel,
    *,
    start_t: float,
    boost_t: float = 55.0,
    boost_percentile: float = 0.4,
    hours: int = 24 * 7,
) -> SimResult:
    slots = [PriceSlot(t, t + timedelta(hours=1), p, PriceSource.ACTUAL_PSTRYK) for t, p in prices]
    last = slots[-1].end
    res = SimResult(strategy)
    t = start_t
    strat = max(0.0, min(cfg.stratification_k, 8.0))
    hp_on_prev = False
    for i in range(min(hours, len(slots))):
        now = slots[i].start
        visible = [s for s in slots[i:] if s.start < _known_until(now, last)]
        t_out = outdoor.get(now, 5.0)
        h = _Hour(t_out, heat_demand_kw(cfg, t_out), slots[i].value or 0.0, 0.0, 0.0, True, None, None)
        level, heater, boosted = 0.0, 0.0, False
        if strategy == "auto":
            level = _auto_level(cfg, t, h)
        elif strategy == "boost":
            plan = plan_boost(
                cfg,
                cop,
                now=now,
                current_t=t,
                slots=visible,
                outdoor_forecast=outdoor,
                boost_t=boost_t,
                boost_percentile=boost_percentile,
            )
            boosted = plan.should_heat
            heater = plan.steps[0].heater_kw if plan.steps else 0.0
            level = 1.0 if boosted else _auto_level(cfg, t, h)
        else:  # full
            plan = plan_buffer(cfg, cop, now=now, current_t=t, slots=visible, outdoor_forecast=outdoor)
            if plan.mode == "fallback" or not plan.steps:
                level = _auto_level(cfg, t, h)
            else:
                level = plan.steps[0].heat_fraction if plan.steps[0].hp_kwh > 0 else 0.0
                heater = plan.steps[0].heater_kw
        run_cfg = replace(cfg, hp_max_t=plan.boost_target_t or boost_t) if boosted else cfg
        r = _step2(run_cfg, cop, t, level, heater, h)
        res.cost += r.cost
        res.electric_kwh += r.e_hp + r.e_heater
        res.heat_kwh += r.q_hp + r.q_heater
        top = r.t_next + strat
        res.min_top = min(res.min_top, top)
        if top < min_at(cfg, t_out) - 0.3:
            res.hours_below_min += 1
        hp_on = r.q_hp > 0.05
        if hp_on and not hp_on_prev:
            res.hp_starts += 1
        hp_on_prev = hp_on
        res.boost_hours += 1 if boosted else 0
        res.trace.append(
            {
                "start": now.isoformat(),
                "price": round(slots[i].value or 0.0, 4),
                "t_out": t_out,
                "t_start": round(t, 2),
                "t_end": round(r.t_next, 2),
                "hp_level": round(level, 2),
                "heater_kw": heater,
                "boost": boosted,
                "electric_kwh": round(r.e_hp + r.e_heater, 3),
                "cost": round(r.cost, 4),
            }
        )
        t = r.t_next
    res.end_t = t
    return res


def optimum(
    prices: Sequence[tuple[datetime, float]],
    outdoor: dict[datetime, float],
    cfg: BufferConfig,
    cop: CopModel,
    *,
    start_t: float,
    hours: int = 24 * 7,
) -> SimResult:
    """Perfect-foresight full control over the whole period (a lower bound)."""
    n = min(hours, len(prices))
    slots = [PriceSlot(t, t + timedelta(hours=1), p, PriceSource.ACTUAL_PSTRYK) for t, p in prices[:n]]
    plan = plan_buffer(
        replace(cfg, max_horizon_h=n), cop, now=slots[0].start, current_t=start_t, slots=slots, outdoor_forecast=outdoor
    )
    res = SimResult("optimum")
    t = start_t
    prev_on = False
    strat = max(0.0, min(cfg.stratification_k, 8.0))
    for slot, step in zip(slots, plan.steps, strict=False):
        t_out = outdoor.get(slot.start, 5.0)
        h = _Hour(t_out, heat_demand_kw(cfg, t_out), slot.value or 0.0, 0.0, 0.0, True, None, None)
        r = _step2(cfg, cop, t, step.heat_fraction if step.hp_kwh > 0 else 0.0, step.heater_kw, h)
        res.cost += r.cost
        res.electric_kwh += r.e_hp + r.e_heater
        res.heat_kwh += r.q_hp + r.q_heater
        res.min_top = min(res.min_top, r.t_next + strat)
        if r.t_next + strat < min_at(cfg, t_out) - 0.3:
            res.hours_below_min += 1
        on = r.q_hp > 0.05
        res.hp_starts += 1 if on and not prev_on else 0
        prev_on = on
        t = r.t_next
    res.end_t = t
    return res


def compare(
    prices,
    outdoor,
    cfg,
    cop,
    *,
    start_t: float,
    boost_t: float = 55.0,
    hours: int = 24 * 7,
    bound: bool = False,
) -> dict[str, dict]:
    out = {}
    for s in ("auto", "boost", "full"):
        out[s] = simulate(s, prices, outdoor, cfg, cop, start_t=start_t, boost_t=boost_t, hours=hours).summary()
    if bound:
        out["optimum"] = optimum(prices, outdoor, cfg, cop, start_t=start_t, hours=hours).summary()
    # value the different end-of-week heat content fairly (at the auto average cost of heat)
    ref = out["auto"]
    unit = (ref["cost_pln"] / ref["heat_kwh"]) if ref["heat_kwh"] else 0.0
    for r in out.values():
        r["end_heat_adjusted_cost_pln"] = round(r["cost_pln"] - (r["end_t"] - ref["end_t"]) * cfg.capacity * unit, 2)
        r["saving_vs_auto_pln"] = round(ref["cost_pln"] - r["end_heat_adjusted_cost_pln"], 2)
    return out
