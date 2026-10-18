"""v0.6.0: heat-pump physics (frost derating, part load, cycling, heating curve),
optimised boost temperature and the perfect-foresight benchmark."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.pstryk_ai.config_flow import validate_section
from custom_components.pstryk_ai.models.price_slot import PriceSlot, PriceSource
from custom_components.pstryk_ai.optimization.boost import boost_targets, plan_boost
from custom_components.pstryk_ai.optimization.heat_pump import CopModel
from custom_components.pstryk_ai.optimization.simulation import compare, simulate
from custom_components.pstryk_ai.optimization.thermal_storage import (
    BufferConfig,
    _Hour,
    _step2,
    hp_capacity_kw,
    min_at,
    part_load_factor,
    plan_buffer,
    setpoint_at,
)
from custom_components.pstryk_ai.settings_ext import hp_levels, load_ext

NOW = datetime(2026, 10, 17, 4, 0, tzinfo=UTC)  # 06:00 local
COP = CopModel(nominal_cop=3.0)


def _cfg(**kw) -> BufferConfig:
    base = {
        "volume_l": 500,
        "min_t": 30,
        "max_t": 60,
        "target_t": 35,
        "hp_thermal_kw": 9,
        "hp_electric_kw": 3,
        "building_kw_per_k": 0.2,
        "max_horizon_h": 48,
        "hp_max_t": 55,
        "hp_levels": hp_levels(30),
    }
    base.update(kw)
    return BufferConfig(**base)


def _hour(t_out: float, cfg: BufferConfig, price: float = 1.0) -> _Hour:
    return _Hour(t_out, cfg.building_kw_per_k * max(0.0, cfg.base_t - t_out), price, 0.0, 0.0, True, None, None)


def _slots(prices: list[float]) -> list[PriceSlot]:
    return [
        PriceSlot(NOW + timedelta(hours=i), NOW + timedelta(hours=i + 1), p, PriceSource.ACTUAL_PSTRYK)
        for i, p in enumerate(prices)
    ]


# ---------------------------------------------------------------- physics
def test_capacity_falls_in_frost() -> None:
    cfg = _cfg()
    assert hp_capacity_kw(cfg, 10) == 9
    assert hp_capacity_kw(cfg, 7) == 9
    assert hp_capacity_kw(cfg, -15) == pytest.approx(9 * (1 - 0.012 * 22))  # generic ≈ 6.6 kW
    assert hp_capacity_kw(_cfg(hp_kw_at_minus15=7.5), -15) == pytest.approx(7.5)
    assert hp_capacity_kw(_cfg(hp_kw_at_minus15=7.5), -4) == pytest.approx(8.25)
    assert hp_capacity_kw(cfg, -60) == pytest.approx(9 * 0.4)  # floor


def test_part_load_cycling_loss_follows_en14825() -> None:
    assert part_load_factor(1.0) == pytest.approx(1.0)
    assert part_load_factor(0.5) == pytest.approx(0.5 / (0.45 + 0.1))
    assert part_load_factor(0.2) < part_load_factor(0.5) < part_load_factor(0.9)


def test_inverter_is_more_efficient_at_part_load() -> None:
    cfg = _cfg()
    h = _hour(5.0, cfg)
    low = _step2(cfg, COP, 35.0, 0.3, 0.0, h)
    full = _step2(cfg, COP, 35.0, 1.0, 0.0, h)
    assert low.cop > full.cop * 1.05  # smaller condenser lift


def test_on_off_compressor_pays_for_cycling() -> None:
    inverter = _cfg()
    on_off = _cfg(hp_levels=(1.0,))
    h = _hour(12.0, inverter)  # mild: ~1.2 kW demand, a fraction of 9 kW
    # holding 35 °C needs only a small share of the capacity
    a = _step2(inverter, COP, 35.0, 0.15, 0.0, h)
    b = _step2(on_off, COP, 35.0, 0.15, 0.0, h)
    assert a.q_hp == pytest.approx(b.q_hp)
    assert b.cop < a.cop  # on/off cycles at 15 % of the hour


def test_heating_curve_shifts_setpoint_and_minimum() -> None:
    flat = _cfg()
    curve = _cfg(curve_slope=0.4)
    assert setpoint_at(flat, -10) == 35 and min_at(flat, -10) == 30
    assert setpoint_at(curve, 0) == pytest.approx(35) and min_at(curve, 0) == pytest.approx(30)
    assert setpoint_at(curve, -10) == pytest.approx(39) and min_at(curve, -10) == pytest.approx(34)
    assert setpoint_at(curve, 10) == pytest.approx(31) and min_at(curve, 10) == pytest.approx(26)
    assert min_at(curve, 40) == pytest.approx(22)  # never below room + 2 K
    assert setpoint_at(curve, -60) <= 55  # never above the heat-pump limit


def test_plan_keeps_weather_dependent_minimum() -> None:
    cfg = _cfg(curve_slope=0.4)
    slots = _slots([0.6] * 6 + [1.4] * 18 + [0.6] * 24)
    outdoor = {s.start: -8.0 for s in slots}
    plan = plan_buffer(cfg, COP, now=NOW, current_t=36.0, slots=slots, outdoor_forecast=outdoor)
    assert plan.feasible
    assert all(s.temperature_end >= min_at(cfg, -8.0) - 0.3 for s in plan.steps)  # 33.2 °C, not 30 °C


# ------------------------------------------------------------ boost target
def _boost(dip: float):
    slots = _slots([dip] * 2 + [1.0] * 46)
    cfg = _cfg(volume_l=200, building_kw_per_k=0.25)
    return plan_boost(
        cfg, COP, now=NOW, current_t=35, slots=slots, outdoor_forecast={s.start: 5.0 for s in slots}, boost_t=55
    )


def test_boost_target_follows_the_depth_of_the_dip() -> None:
    deep, moderate, small = _boost(0.3), _boost(0.5), _boost(0.7)
    assert deep.boost_hours and deep.target_temperature == pytest.approx(55, abs=0.5)
    assert moderate.boost_hours and moderate.target_temperature < 55  # a hotter tank would cost more COP than it saves
    assert not small.boost_hours  # 30 % spread: not worth it
    assert "do 50 °C" in moderate.optimization_reason or "do 45 °C" in moderate.optimization_reason


def test_boost_targets_are_spaced_and_bounded() -> None:
    assert boost_targets(_cfg(), 55, 35) == [40, 45, 50, 55]
    assert boost_targets(_cfg(), 45, 40) == [45]


# ------------------------------------------------------------ simulation
def _week(dips: list[float]) -> tuple[list[tuple[datetime, float]], dict[datetime, float]]:
    start = datetime(2026, 1, 5, 5, 0, tzinfo=UTC)  # 06:00 local
    day = [
        1.2,
        1.3,
        1.2,
        1.0,
        0.9,
        0,
        0,
        0,
        0,
        0.9,
        1.0,
        1.2,
        1.4,
        1.4,
        1.3,
        1.1,
        1.0,
        0.95,
        0.9,
        0.9,
        0.9,
        0.9,
        0.95,
        1.1,
    ]
    prices, outdoor = [], {}
    for d, dip in enumerate([*dips, dips[-1]]):
        for i, p in enumerate(day):
            t = start + timedelta(days=d, hours=i)
            prices.append((t, dip if 5 <= i <= 8 else p))
            outdoor[t] = -12.0 + 3.0 * (i > 8 and i < 18)
    return prices, outdoor


def test_cold_week_keeps_comfort_with_derated_heat_pump() -> None:
    prices, outdoor = _week([0.5, 0.7, 0.4, 0.8, 0.6])
    cfg = _cfg(curve_slope=0.3)
    for strategy in ("auto", "boost", "full"):
        res = simulate(strategy, prices, outdoor, cfg, COP, start_t=40, hours=24 * 5)
        assert res.hours_below_min == 0, strategy


def test_closed_loop_is_close_to_the_perfect_foresight_optimum() -> None:
    prices, outdoor = _week([0.5, 0.7, 0.4, 0.8, 0.6])
    res = compare(prices, outdoor, _cfg(), COP, start_t=40, hours=24 * 5, bound=True)
    best = res["optimum"]["end_heat_adjusted_cost_pln"]
    full = res["full"]["end_heat_adjusted_cost_pln"]
    assert best <= full * 1.01  # the bound is (numerically) a lower bound
    assert full <= best * 1.03  # MPC with day-ahead prices loses < 3 % to perfect foresight
    assert res["boost"]["end_heat_adjusted_cost_pln"] < res["auto"]["cost_pln"]


# ------------------------------------------------------------ options
def test_options_reach_the_model() -> None:
    x = load_ext({"heat_pump_thermal_power_minus15": "6,5", "heating_curve_slope": 0.35})
    assert x.hp_kw_minus15 == 6.5 and x.curve_slope == 0.35
    assert load_ext({"heat_pump_thermal_power_minus15": ""}).hp_kw_minus15 is None
    assert validate_section("buffer", {"heat_pump_thermal_power_minus15": "abc"}) == {
        "heat_pump_thermal_power_minus15": "invalid_number"
    }
