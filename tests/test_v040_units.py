"""v0.4.0 unit tests: tariff zones, storages, heaters, CWU, heat system, learning, spends, PV."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.pstryk_ai.learning import HourSample, fit_cop_ratio, fit_draw_profile, fit_losses
from custom_components.pstryk_ai.models.energy_data import MeterFrame
from custom_components.pstryk_ai.models.price_slot import PriceSlot, PriceSource
from custom_components.pstryk_ai.optimization.dhw import (
    daily_draw_kwh,
    draw_series,
    legionella_due,
    parse_times,
    ready_constraints,
)
from custom_components.pstryk_ai.optimization.heat_pump import CopModel
from custom_components.pstryk_ai.optimization.heat_system import VALVE_DHW, StorageInput, plan_heat_system
from custom_components.pstryk_ai.optimization.thermal_storage import (
    BufferConfig,
    HeaterConfig,
    ReadyConstraint,
    mean_from_layers,
    plan_buffer,
    storage_soc,
)
from custom_components.pstryk_ai.pv import PvConfig, device_price, pv_forecast, surplus
from custom_components.pstryk_ai.settings_ext import load_ext, parse_steps
from custom_components.pstryk_ai.spends import daily_totals, monthly_totals, summarize
from custom_components.pstryk_ai.statistics import build_rows
from custom_components.pstryk_ai.tariff import DistributionTariff, Tariff, parse_hour_ranges

from .conftest import local_midnight_utc

NOW = datetime(2026, 10, 16, 20, 0, tzinfo=UTC)  # 22:00 local (Friday)


def _slots(values: list[float], start: datetime = NOW) -> list[PriceSlot]:
    return [
        PriceSlot(start + timedelta(hours=i), start + timedelta(hours=i + 1), v, PriceSource.ACTUAL_PSTRYK)
        for i, v in enumerate(values)
    ]


# ------------------------------------------------------------------ tariff zones
def test_hour_ranges_and_zones() -> None:
    assert parse_hour_ranges("22-6,13-15") == {22, 23, 0, 1, 2, 3, 4, 5, 13, 14}
    assert parse_hour_ranges("garbage") == set()
    g12w = DistributionTariff("G12w", 0.30, 0.10, 0.0, parse_hour_ranges("22-6,13-15"), set(), weekend_offpeak=True)
    friday_noon = datetime(2026, 10, 16, 10, tzinfo=UTC)  # 12:00 local
    saturday_noon = datetime(2026, 10, 17, 10, tzinfo=UTC)
    assert g12w.zone(friday_noon) == "peak" and g12w.rate(friday_noon) == 0.30
    assert g12w.zone(saturday_noon) == "offpeak"
    assert g12w.zone(datetime(2026, 10, 16, 11, 30, tzinfo=UTC)) == "offpeak"  # 13:30 local
    g13 = DistributionTariff("G13", 0.3, 0.1, 0.4, parse_hour_ranges("21-7"), parse_hour_ranges("16-21"))
    assert g13.zone(datetime(2026, 10, 16, 15, tzinfo=UTC)) == "peak2"  # 17:00 local


def test_tariff_all_in_by_zone() -> None:
    t = Tariff(vat_rate=0.23, distribution=DistributionTariff("G12", 0.30, 0.10, 0.0, parse_hour_ranges("22-6")))
    night = datetime(2026, 10, 16, 22, tzinfo=UTC)  # 00:00 local
    day = datetime(2026, 10, 16, 10, tzinfo=UTC)
    assert t.all_in(0.5, night) == pytest.approx(0.5 + 0.10 * 1.23)
    assert t.all_in(0.5, day) == pytest.approx(0.5 + 0.30 * 1.23)
    shifted = t.all_in_slots(_slots([0.5, 0.5], night))
    assert shifted[0].value == pytest.approx(0.5 + 0.123)
    assert t.distribution_zone(night) == "offpeak"


# ---------------------------------------------------------------- storages
def test_layers_and_soc() -> None:
    assert mean_from_layers(50, 30) == (40, 10)
    assert mean_from_layers(45, None) == (45, 0.0)
    assert mean_from_layers(None, None) == (None, 0.0)
    assert storage_soc(BufferConfig(min_t=30, max_t=50), 40) == pytest.approx(50)


def test_heater_used_when_power_is_negative() -> None:
    cfg = BufferConfig(max_horizon_h=24, building_kw_per_k=0.1, heater=HeaterConfig(steps_kw=[2, 4]), hp_max_t=45)
    prices = [0.8] * 24
    prices[2] = -0.2
    plan = plan_buffer(cfg, CopModel(), now=NOW, current_t=38, slots=_slots(prices), outdoor_forecast={})
    assert plan.steps[2].heater_kw > 0  # free (negative) energy -> run the element too
    assert all(s.temperature_end <= cfg.max_t + 1e-6 for s in plan.steps)


def test_heater_reaches_above_heat_pump_limit_for_legionella() -> None:
    cfg = BufferConfig(
        name="dhw",
        volume_l=200,
        min_t=40,
        max_t=65,
        target_t=50,
        hp_max_t=55,
        building_kw_per_k=0.0,
        demand_kw=[0.1] * 24,
        heater=HeaterConfig(steps_kw=[3]),
        legionella_t=60,
        legionella_deadline_h=24,
        max_horizon_h=24,
    )
    plan = plan_buffer(cfg, CopModel(), now=NOW, current_t=48, slots=_slots([0.5] * 24), outdoor_forecast={})
    assert plan.legionella_at is not None
    assert max(s.temperature_end for s in plan.steps) >= 59.8
    assert sum(s.heater_kw for s in plan.steps) > 0  # the pump alone cannot exceed 55 °C


def test_gas_heater_cost_is_fuel_not_electricity() -> None:
    cfg = BufferConfig(
        hp_enabled=False,
        building_kw_per_k=0.2,
        heater=HeaterConfig(kind="gas", steps_kw=[10], efficiency=0.9, fuel_price=0.30),
        max_horizon_h=12,
    )
    plan = plan_buffer(cfg, CopModel(), now=NOW, current_t=31, slots=_slots([2.0] * 12), outdoor_forecast={})
    heating = [s for s in plan.steps if s.heater_kw > 0]
    assert heating and all(s.electric_kwh == 0 for s in heating)
    assert all(s.fuel_cost == pytest.approx(s.heater_kw / 0.9 * 0.30, rel=1e-6) for s in heating)
    assert plan.fuel_cost_pln > 0


def test_power_cap_is_respected() -> None:
    cfg = BufferConfig(building_kw_per_k=0.3, heater=HeaterConfig(steps_kw=[3, 6]), max_horizon_h=24)
    plan = plan_buffer(
        cfg, CopModel(), now=NOW, current_t=31, slots=_slots([0.2] * 24), outdoor_forecast={}, cap_kw=[4.0] * 24
    )
    assert all(s.electric_kwh <= 4.0 + 1e-6 for s in plan.steps)


def test_ready_constraint_is_met() -> None:
    ready_at = NOW + timedelta(hours=8)
    cfg = BufferConfig(
        name="dhw",
        volume_l=200,
        min_t=35,
        max_t=60,
        target_t=50,
        building_kw_per_k=0.0,
        demand_kw=[0.2] * 24,
        ready=[ReadyConstraint(ready_at, 52)],
        max_horizon_h=24,
    )
    prices = [0.2] * 3 + [1.5] * 21  # cheap early hours only
    plan = plan_buffer(cfg, CopModel(), now=NOW, current_t=40, slots=_slots(prices), outdoor_forecast={})
    hour = next(s for s in plan.steps if s.start < ready_at <= s.start + timedelta(hours=1))
    assert hour.temperature_end >= 51.5
    assert plan.feasible


def test_stratification_counts_for_comfort() -> None:
    # mean 32 °C but top 40 °C: no forced heating at expensive prices
    cfg = BufferConfig(min_t=33, building_kw_per_k=0.0, max_horizon_h=6, stratification_k=8)
    plan = plan_buffer(cfg, CopModel(), now=NOW, current_t=32, slots=_slots([2.0] * 6), outdoor_forecast={})
    assert not plan.should_heat


def test_pv_surplus_makes_heating_cheaper() -> None:
    cfg = BufferConfig(building_kw_per_k=0.2, max_horizon_h=12)
    start = NOW
    surplus_map = {start + timedelta(hours=5): 5.0, start + timedelta(hours=6): 5.0}
    sell = dict.fromkeys(surplus_map, 0.1)
    plan = plan_buffer(
        cfg,
        CopModel(),
        now=NOW,
        current_t=36,
        slots=_slots([0.9] * 12),
        outdoor_forecast={},
        sell_prices=sell,
        surplus_kwh=surplus_map,
    )
    heated = {s.start for s in plan.steps if s.hp_kwh > 0}
    assert set(surplus_map) & heated


def test_heat_system_valve_is_exclusive_and_priority() -> None:
    buffer = BufferConfig(building_kw_per_k=0.3, max_horizon_h=24)
    dhw = BufferConfig(
        name="dhw",
        volume_l=200,
        min_t=40,
        max_t=55,
        target_t=48,
        building_kw_per_k=0.0,
        demand_kw=[0.3] * 24,
        max_horizon_h=24,
    )
    plan = plan_heat_system(
        {"buffer": StorageInput(buffer, 34.0), "dhw": StorageInput(dhw, 42.0)},
        CopModel(),
        now=NOW,
        slots=_slots([0.4 + 0.02 * (i % 6) for i in range(24)]),
        outdoor_forecast={},
        shared_hp=True,
        priority="dhw",
        power_limit_kw=6.0,
        other_load_kw={},
    )
    b, d = plan.plans["buffer"].steps, plan.plans["dhw"].steps
    assert not any(x.hp_kwh > 0 and y.hp_kwh > 0 for x, y in zip(b, d, strict=False))
    assert all(x.electric_kwh + y.electric_kwh <= 6.0 + 1e-6 for x, y in zip(b, d, strict=False))
    positions = {p for _, p in plan.valve}
    assert positions <= {"buffer", "dhw", "idle"}
    assert plan.valve_records()[0]["position"] in positions
    assert any(p == VALVE_DHW for _, p in plan.valve)


def test_heat_system_fallback_reason() -> None:
    plan = plan_heat_system(
        {"buffer": StorageInput(BufferConfig(), None)},
        CopModel(),
        now=NOW,
        slots=_slots([0.5] * 6),
        outdoor_forecast={},
        fallback_reason={"buffer": "brak odczytu"},
    )
    assert plan.plans["buffer"].mode == "fallback" and plan.plans["buffer"].optimization_reason == "brak odczytu"


# -------------------------------------------------------------------- CWU
def test_dhw_helpers() -> None:
    assert parse_times("06:00, 19:30;x, 25:00") == [(6, 0), (19, 30)]
    hours = [local_midnight_utc(2026, 10, 17) + timedelta(hours=i) for i in range(24)]
    series = draw_series(hours, 150)
    assert sum(series) == pytest.approx(daily_draw_kwh(150))
    rc = ready_constraints(NOW, [(6, 0)], 45, horizon_h=48)
    assert len(rc) == 2 and all(r.min_t == 45 for r in rc)
    assert legionella_due(None, NOW) == (True, 24)
    due, _ = legionella_due(NOW - timedelta(days=2), NOW)
    assert not due
    due, hours_left = legionella_due(NOW - timedelta(days=6, hours=12), NOW)
    assert due and hours_left == 12


# ---------------------------------------------------------------- learning
def _samples(k: float, u: float, cap: float, n: int = 60) -> list[HourSample]:
    rows = []
    t = 45.0
    for i in range(n):
        t_out = -5 + (i % 15)
        drop = (k * max(0, 18 - t_out) + u * (t - 20)) / cap
        rows.append(HourSample(NOW + timedelta(hours=i), t, t - drop, t_out, 0.0, 0.0, False))
        t = t - drop if t - drop > 30 else 45.0
    return rows


def test_fit_losses_recovers_parameters() -> None:
    fit = fit_losses(_samples(0.25, 0.004, 0.58), 0.58, 18.0)
    assert fit is not None
    assert fit["building_kw_per_k"] == pytest.approx(0.25, rel=0.05)
    assert fit["loss_kw_per_k"] == pytest.approx(0.004, rel=0.2)
    assert fit_losses(_samples(0.25, 0.004, 0.58, n=10), 0.58, 18.0) is None


def test_fit_draw_profile_and_cop() -> None:
    rows = []
    for day in range(3):
        for h in range(24):
            start = local_midnight_utc(2026, 10, 10 + day) + timedelta(hours=h)
            draw = 1.0 if h in (6, 7, 19) else 0.0
            rows.append(HourSample(start, 50.0, 50.0 - draw / 0.2326, 10.0, 0.0, 0.0, False))
    prof = fit_draw_profile(rows, 0.2326, 0.0)
    assert prof is not None and prof[7] == pytest.approx(1.0, abs=0.01) and prof[12] == pytest.approx(0.0, abs=0.01)
    cop = CopModel(nominal_cop=3.0)
    heating = []
    for i in range(20):
        t0, t1, t_out = 35.0, 40.0, 5.0
        heat = (t1 - t0) * 0.58
        measured = cop.cop(t_out, (t0 + t1) / 2 + 5) * 0.8
        heating.append(HourSample(NOW + timedelta(hours=i), t0, t1, t_out, heat / measured, 0.0, True))
    assert fit_cop_ratio(heating, 0.58, 0.0, cop.cop) == pytest.approx(0.8, abs=0.01)


# ------------------------------------------------------------------ spends
def _day_frame(day: int, cost: float, live: bool = False) -> MeterFrame:
    start = local_midnight_utc(2026, 10, day)
    return MeterFrame(
        start,
        start + timedelta(days=1),
        10.0,
        1.0,
        9.0,
        {
            "energy_import_cost": cost,
            "energy_sold_value": 0.5,
            "energy_balance_value": 0.5 - cost,
            "vat": cost * 0.18,
            "var_dist_cost_net": 1.0,
        },
        live,
    )


def test_spends_summary() -> None:
    days = daily_totals([_day_frame(d, 5.0 + d) for d in range(1, 16)] + [_day_frame(16, 3.0, live=True)])
    assert set(days) >= {"2026-10-01", "2026-10-16"}
    sep = local_midnight_utc(2026, 9, 1)
    months = monthly_totals([MeterFrame(sep, sep + timedelta(days=30), 300, 20, 280, {"energy_import_cost": 250.0})])
    s = summarize(days, months, datetime(2026, 10, 16, 18, tzinfo=UTC))
    assert s.today.cost == 3.0 and s.yesterday.cost == 20.0
    assert s.previous_month["cost"] == 250.0
    complete = [5.0 + d for d in range(1, 16)]
    assert s.avg_daily_cost == pytest.approx(sum(complete) / 15, abs=1e-3)
    assert s.projected_month_cost == pytest.approx(sum(complete) + 3.0 + 15 * s.avg_daily_cost, abs=0.05)
    assert s.breakdown_month["var_dist_cost_net"] == pytest.approx(16.0)
    rows = build_rows(days, "cost")
    assert rows[-1]["sum"] == pytest.approx(sum(complete) + 3.0)
    assert rows[0]["start"].hour == 0 and rows[0]["start"].tzinfo is not None


# ---------------------------------------------------------------------- PV
def test_pv_forecast_and_device_price() -> None:
    from custom_components.pstryk_ai.api.weather import WeatherHour

    w = [
        WeatherHour(NOW, {"shortwave_radiation": 800.0}),
        WeatherHour(NOW + timedelta(hours=1), {"shortwave_radiation": 0.0}),
    ]
    cfg = PvConfig(kwp=5, performance_ratio=0.8, base_load_kw=0.5)
    prod = pv_forecast(w, cfg)
    assert prod[NOW] == pytest.approx(3.2)
    sur = surplus(prod, cfg)
    assert sur[NOW] == pytest.approx(2.7)
    slot = _slots([0.8])[0]
    assert device_price(slot, 0.2, 2.7, 2.0) == pytest.approx(0.2)
    assert device_price(slot, 0.2, 1.0, 2.0) == pytest.approx(0.5)


def test_settings_ext_defaults_and_parsing() -> None:
    x = load_ext({})
    assert not x.dhw.enabled and not x.buffer_heater.enabled and x.spends and x.distribution is None
    x = load_ext(
        {
            "buffer_heater_enabled": True,
            "buffer_heater_kind": "gas",
            "buffer_heater_steps_kw": "6, 3,x",
            "distribution_tariff": "G12w",
            "dhw_ready_times": "07:15",
        }
    )
    assert x.buffer_heater.config.stages == [0.0, 3.0, 6.0]
    assert x.buffer_heater.config.efficiency == pytest.approx(0.92)
    assert x.distribution is not None and x.distribution.weekend_offpeak
    assert x.dhw.ready_times == [(7, 15)]
    assert parse_steps("2;4,4") == [2.0, 4.0]
