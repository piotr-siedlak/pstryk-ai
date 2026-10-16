"""Cheapest-hours search, device scheduler, COP model and thermal buffer optimiser."""

from __future__ import annotations

from datetime import UTC, datetime, time, timedelta

import pytest

from custom_components.pstryk_ai.models.optimizer import DeviceProfile
from custom_components.pstryk_ai.models.price_slot import PriceSlot, PriceSource
from custom_components.pstryk_ai.optimization.cheapest_hours import (
    best_window,
    cheapest_n,
    classify,
    effective_price,
)
from custom_components.pstryk_ai.optimization.heat_pump import CopModel, parse_cop_curve
from custom_components.pstryk_ai.optimization.scheduler import schedule_device
from custom_components.pstryk_ai.optimization.thermal_storage import (
    BufferConfig,
    plan_buffer,
    thermal_energy_kwh,
)

NOW = datetime(2026, 10, 16, 20, 0, tzinfo=UTC)  # 22:00 local


def slots(
    values: list[float | None], start: datetime = NOW, source: PriceSource = PriceSource.ACTUAL_PSTRYK
) -> list[PriceSlot]:
    return [
        PriceSlot(
            start + timedelta(hours=i),
            start + timedelta(hours=i + 1),
            v,
            source if v is not None else PriceSource.UNAVAILABLE,
        )
        for i, v in enumerate(values)
    ]


def test_best_window_across_midnight() -> None:
    s = slots([0.9, 0.8, 0.2, 0.1, 0.15, 0.9, 0.9])  # cheapest crosses local midnight
    w = best_window(s, 3, now=NOW)
    assert w.start == NOW + timedelta(hours=2)
    assert w.average_price == pytest.approx(0.15)


def test_best_window_multi_day_and_deadline() -> None:
    values = [0.5] * 60
    values[50:52] = [0.1, 0.1]
    s = slots(values)
    assert best_window(s, 2, now=NOW).start == NOW + timedelta(hours=50)
    w = best_window(s, 2, now=NOW, deadline=NOW + timedelta(hours=24))
    assert w.start < NOW + timedelta(hours=24)


def test_window_skips_gaps_and_unavailable() -> None:
    s = slots([0.1, None, 0.1, 0.1, 0.5])
    w = best_window(s, 2, now=NOW)
    assert w.start == NOW + timedelta(hours=2)


def test_speculative_postponement_avoided_when_within_uncertainty() -> None:
    near = slots([0.50] * 24)
    far = [
        PriceSlot(
            NOW + timedelta(hours=24 + i),
            NOW + timedelta(hours=25 + i),
            0.48,
            PriceSource.MODEL_FORECAST,
            p10=0.2,
            p50=0.48,
            p90=0.8,
        )
        for i in range(48)
    ]
    w = best_window(near + far, 3, now=NOW, max_speculative_hours=24)
    assert w.start < NOW + timedelta(hours=24)  # 0.02 saving is far below forecast uncertainty
    far_cheap = [PriceSlot(s.start, s.end, 0.05, PriceSource.MODEL_FORECAST, p10=0.03, p50=0.05, p90=0.07) for s in far]
    w2 = best_window(near + far_cheap, 3, now=NOW, max_speculative_hours=24)
    assert w2.start >= NOW + timedelta(hours=24)


def test_risk_adjusted_price() -> None:
    s = PriceSlot(NOW, NOW + timedelta(hours=1), 0.5, PriceSource.MODEL_FORECAST, p10=0.3, p50=0.5, p90=0.9)
    assert effective_price(s, 0.5) == pytest.approx(0.7)
    s2 = PriceSlot(NOW, NOW + timedelta(hours=1), 0.5, PriceSource.ACTUAL_PSTRYK)
    assert effective_price(s2, 0.5) == 0.5


def test_cheapest_n_non_consecutive_and_most_expensive() -> None:
    s = slots([0.5, 0.1, 0.9, 0.2, 0.8, 0.05])
    w = cheapest_n(s, 3, now=NOW)
    assert [h.hour for h in w.slots] == [21, 23, 1]
    exp = cheapest_n(s, 2, now=NOW, most_expensive=True)
    assert exp.average_price == pytest.approx(0.85)
    assert best_window(s, 1, now=NOW, most_expensive=True).average_price == 0.9


def test_classify_thresholds() -> None:
    s = slots([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8])
    flags = classify(s[0], s, absolute_threshold=0.15)
    assert flags == {"cheap": True, "expensive": False, "below_absolute": True}
    assert classify(s[-1], s)["expensive"] is True


def test_scheduler_min_run_and_off() -> None:
    values = [0.1, 0.9, 0.1, 0.9, 0.1, 0.9, 0.2, 0.2, 0.9, 0.9]
    prof = DeviceProfile("Pompa", power_kw=2, duration_h=4, min_run_h=2, min_off_h=1)
    res = schedule_device(prof, slots(values), NOW, default_horizon_h=10)
    assert res.feasible
    hours = sorted(res.slots)
    # every run must be >= 2 hours
    runs, cur = [], [hours[0]]
    for h in hours[1:]:
        if h - cur[-1] == timedelta(hours=1):
            cur.append(h)
        else:
            runs.append(cur)
            cur = [h]
    runs.append(cur)
    assert all(len(r) >= 2 for r in runs)
    assert len(hours) == 4
    assert res.expected_energy_kwh == 8


def test_scheduler_deadline_allowed_hours_and_max_price() -> None:
    values = [0.1] * 4 + [0.3] * 20
    prof = DeviceProfile(
        "Bojler", power_kw=1, duration_h=2, allowed_start=time(2, 0), allowed_end=time(6, 0), max_price=0.35
    )
    res = schedule_device(prof, slots(values), NOW, default_horizon_h=24)
    assert res.feasible
    for h in res.slots:
        assert 2 <= h.astimezone(__import__("zoneinfo").ZoneInfo("Europe/Warsaw")).hour < 6
    prof_too_cheap = DeviceProfile("X", duration_h=3, max_price=0.05)
    assert not schedule_device(prof_too_cheap, slots(values), NOW).feasible


def test_scheduler_fallback_without_prices() -> None:
    res = schedule_device(DeviceProfile("EV", duration_h=2), slots([None] * 10), NOW, default_horizon_h=10)
    assert res.feasible and "awaryjny" in res.reason
    assert res.slots[0] == NOW


def test_scheduler_consecutive_profile() -> None:
    res = schedule_device(DeviceProfile("Zmywarka", duration_h=2, consecutive=True), slots([0.5, 0.1, 0.1, 0.5]), NOW)
    assert res.slots == [NOW + timedelta(hours=1), NOW + timedelta(hours=2)]


def test_cop_model_supply_temperature_reduces_cop() -> None:
    cop = CopModel(nominal_cop=4.0)
    assert cop.cop(7, 35) == pytest.approx(4.0)
    assert cop.cop(7, 55) < cop.cop(7, 35)
    assert cop.cop(-10, 35) < cop.cop(7, 35)
    curve = CopModel(curve=parse_cop_curve("-15:2.0, -7:2.6, 2:3.3, 7:4.1"))
    assert curve.cop(-7, 35) == pytest.approx(2.6)
    assert 2.6 < curve.cop(0, 35) < 3.3


def test_thermal_energy_formula() -> None:
    assert thermal_energy_kwh(500, 10) == pytest.approx(5.815)


def _buffer_slots(prices: list[float]) -> list[PriceSlot]:
    return slots(prices, start=NOW.replace(minute=0))


def test_buffer_respects_temperature_limits() -> None:
    cfg = BufferConfig(volume_l=500, min_t=30, max_t=50, hp_thermal_kw=9, building_kw_per_k=0.15, max_horizon_h=48)
    prices = [0.9 if (i // 6) % 2 else 0.1 for i in range(48)]
    plan = plan_buffer(cfg, CopModel(), now=NOW, current_t=40, slots=_buffer_slots(prices), outdoor_forecast={})
    assert plan.feasible
    assert all(s.temperature_end <= cfg.max_t + 1e-6 for s in plan.steps)
    assert min(s.temperature_end for s in plan.steps) >= cfg.min_t - 0.5
    heated_cheap = sum(s.thermal_kwh for s in plan.steps if s.price < 0.5)
    heated_exp = sum(s.thermal_kwh for s in plan.steps if s.price >= 0.5)
    assert heated_cheap > heated_exp
    assert plan.expected_savings_pln >= -0.01


def test_buffer_min_runtime() -> None:
    cfg = BufferConfig(min_runtime_h=2, min_offtime_h=1, max_horizon_h=36, building_kw_per_k=0.2)
    prices = [0.2 if i % 3 == 0 else 0.6 for i in range(36)]
    plan = plan_buffer(cfg, CopModel(), now=NOW, current_t=35, slots=_buffer_slots(prices), outdoor_forecast={})
    on = [s.heat_fraction > 0 or s.thermal_kwh > 0 for s in plan.steps]
    runs, cur = [], 0
    for flag in [*on, False]:
        if flag:
            cur += 1
        elif cur:
            runs.append(cur)
            cur = 0
    # a run may be truncated only by reaching max temperature, never shorter than min runtime otherwise
    assert all(r >= 2 for r in runs[:-1]) or not runs


def test_buffer_stale_data_never_heats() -> None:
    plan = plan_buffer(
        BufferConfig(),
        CopModel(),
        now=NOW,
        current_t=20,
        slots=_buffer_slots([0.1] * 24),
        outdoor_forecast={},
        stale=True,
    )
    assert plan.should_heat is False
    assert plan.mode == "fallback"
    plan2 = plan_buffer(BufferConfig(), CopModel(), now=NOW, current_t=20, slots=[], outdoor_forecast={})
    assert plan2.should_heat is False and plan2.mode == "fallback"


def test_buffer_heats_now_when_cold_and_cheap() -> None:
    plan = plan_buffer(
        BufferConfig(), CopModel(), now=NOW, current_t=31, slots=_buffer_slots([0.1] + [0.9] * 23), outdoor_forecast={}
    )
    assert plan.should_heat
    assert plan.recommended_start == NOW
    assert plan.target_temperature <= BufferConfig().max_t
    assert plan.to_dict()["schedule"]
