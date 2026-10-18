"""v0.4.1 regression tests built from a real user screenshot (Sat 17.10, 21:00).

Situation: buffer at 7 % (top 31.7 °C, bottom 28.8 °C, minimum 28 °C), price
1.239 zł/kWh now ("expensive"), cheapest window tomorrow 11–14 (~0.78).
Problems found: full-power 9 kW bursts at expensive hours, a false reason
("lowest heat cost"), a planned dip below the minimum and inflated savings
against a thermostat with higher comfort.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.pstryk_ai.models.price_slot import PriceSlot, PriceSource
from custom_components.pstryk_ai.optimization.heat_pump import CopModel
from custom_components.pstryk_ai.optimization.thermal_storage import BufferConfig, plan_buffer
from custom_components.pstryk_ai.settings_ext import hp_levels

NOW = datetime(2026, 10, 17, 19, 5, tzinfo=UTC)  # 21:05 local
SAT = [1.239, 1.165, 1.11]
SUN = [1.13, 1.06, 1.05, 1.04, 1.04, 1.03, 1.03, 1.0, 0.99, 0.84, 0.83, 0.81,
       0.79, 0.77, 0.85, 0.94, 1.04, 1.10, 1.17, 1.12, 1.10, 1.02, 1.04, 1.01]  # fmt: skip


def _slots(prices: list[float]) -> list[PriceSlot]:
    start = NOW.replace(minute=0)
    return [
        PriceSlot(start + timedelta(hours=i), start + timedelta(hours=i + 1), p, PriceSource.ACTUAL_PSTRYK)
        for i, p in enumerate(prices)
    ]


def _cfg(levels: tuple[float, ...]) -> BufferConfig:
    return BufferConfig(
        min_t=28,
        max_t=60,
        target_t=40,
        hp_thermal_kw=9,
        hp_electric_kw=3,
        building_kw_per_k=0.25,
        stratification_k=1.45,
        max_horizon_h=72,
        hp_levels=levels,
    )


def _plan(levels: tuple[float, ...]):
    slots = _slots(SAT + SUN + SUN)
    outdoor = {s.start: 8.0 for s in slots}
    return plan_buffer(
        _cfg(levels), CopModel(nominal_cop=3.0), now=NOW, current_t=30.25, slots=slots, outdoor_forecast=outdoor
    )


def test_modulation_holds_minimum_cheaply_instead_of_bursts() -> None:
    onoff = _plan((1.0,))
    inverter = _plan(hp_levels(30))
    assert inverter.should_heat
    assert inverter.hp_modulation_pct == 30  # just enough at the expensive hour
    assert inverter.steps[0].thermal_kwh < 4.0
    assert inverter.expected_cost_pln < onoff.expected_cost_pln * 0.85  # ≥ 15 % cheaper over 24 h


def test_minimum_is_respected() -> None:
    for levels in ((1.0,), hp_levels(30)):
        plan = _plan(levels)
        tops = [s.temperature_end + 1.45 for s in plan.steps]
        assert min(tops) >= 28 - 0.3, levels
        assert "prognozowany spadek poniżej minimum" not in plan.optimization_reason


def test_reason_states_the_real_cause() -> None:
    plan = _plan(hp_levels(30))
    assert plan.optimization_reason.startswith("Grzanie konieczne")
    assert "cena wysoka" in plan.optimization_reason
    assert "moc 30%" in plan.optimization_reason
    assert "najniższy koszt ciepła" not in plan.optimization_reason


def test_reason_cheap_energy_and_precharge() -> None:
    cfg = BufferConfig(min_t=30, max_t=55, building_kw_per_k=0.1, max_horizon_h=24, hp_levels=(1.0,))
    cheap_now = [0.2] + [1.2] * 23
    plan = plan_buffer(cfg, CopModel(), now=NOW, current_t=40, slots=_slots(cheap_now), outdoor_forecast={})
    assert plan.should_heat and plan.optimization_reason.startswith("Tania energia teraz")
    precharge = [0.6, 0.6, 0.6, 0.6, 0.6, 0.6, 1.6, 1.6, 1.6, 1.6, 1.6, 1.6] + [0.2] * 12
    plan = plan_buffer(cfg, CopModel(), now=NOW, current_t=36, slots=_slots(precharge), outdoor_forecast={})
    assert plan.should_heat
    assert plan.optimization_reason.startswith(("Ładowanie przed droższymi", "Grzanie konieczne", "Tania energia"))


def test_savings_are_measured_against_the_same_minimum() -> None:
    # the old reference held ~40 °C (higher comfort) and inflated savings; the fair one keeps the same minimum
    plan = _plan(hp_levels(30))
    assert 0 <= plan.expected_savings_pln < 8


@pytest.mark.parametrize(
    ("pct", "expected"),
    [(100, (1.0,)), (30, (0.3, 0.48, 0.65, 0.82, 1.0)), (50, (0.5, 0.62, 0.75, 0.88, 1.0))],
)
def test_modulation_levels(pct: int, expected: tuple[float, ...]) -> None:
    assert hp_levels(pct) == expected
