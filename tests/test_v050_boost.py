"""v0.5.0: heat pump strategy "boost only" + 7-day closed-loop simulation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import math

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.pstryk_ai.api import pstryk as pstryk_api
from custom_components.pstryk_ai.models.price_slot import PriceSlot, PriceSource
from custom_components.pstryk_ai.optimization.boost import plan_boost
from custom_components.pstryk_ai.optimization.heat_pump import CopModel
from custom_components.pstryk_ai.optimization.heat_system import StorageInput, plan_heat_system
from custom_components.pstryk_ai.optimization.simulation import compare, simulate
from custom_components.pstryk_ai.optimization.thermal_storage import BufferConfig
from custom_components.pstryk_ai.settings_ext import hp_levels

from .test_init import PSTRYK_URL, PstrykMock, _entry, _mock_public_apis, _setup

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
        "building_kw_per_k": 0.25,
        "max_horizon_h": 48,
        "hp_max_t": 55,
        "hp_levels": hp_levels(30),
    }
    base.update(kw)
    return BufferConfig(**base)


def _slots(prices: list[float], start: datetime = NOW) -> list[PriceSlot]:
    return [
        PriceSlot(start + timedelta(hours=i), start + timedelta(hours=i + 1), p, PriceSource.ACTUAL_PSTRYK)
        for i, p in enumerate(prices)
    ]


def _plan(prices: list[float], t: float = 35.0, **kw):
    slots = _slots(prices)
    return plan_boost(
        _cfg(), COP, now=NOW, current_t=t, slots=slots, outdoor_forecast={s.start: 5.0 for s in slots}, boost_t=55, **kw
    )


def _day(dip: float) -> list[float]:
    """Local 06:00 … 05:00: morning peak, midday dip, evening peak, night."""
    return [1.2, 1.3, 1.2, 1.0, 0.9, dip, dip, dip, dip, 0.9, 1.0, 1.2, 1.4, 1.4, 1.3, 1.1, 1.0, 0.95,
            0.9, 0.9, 0.9, 0.9, 0.95, 1.1]  # fmt: skip


def test_no_boost_on_small_spread() -> None:
    plan = _plan([1.0, 0.95, 1.05, 0.98] * 12)
    assert plan.strategy == "boost"
    assert not plan.should_heat and not plan.boost_hours
    assert plan.optimization_reason.startswith("Pompa pracuje samodzielnie")
    assert plan.expected_savings_pln == pytest.approx(0.0, abs=0.01)


def test_boost_in_large_midday_dip() -> None:
    plan = _plan(_day(0.3) * 2)
    assert plan.boost_hours, "a 0.3 vs 1.2 spread must be used"
    local_hours = {(t + timedelta(hours=2)).hour for t in plan.boost_hours}
    # the dip (11–14) does the charging; topping up at 0.9 right after is still cheaper heat than 1.4 later
    assert local_hours <= {11, 12, 13, 14, 15}
    assert len(local_hours & {11, 12, 13, 14}) >= 2
    assert plan.expected_savings_pln > 1.0
    assert plan.optimization_reason.startswith("Pompa pracuje samodzielnie – doładowanie od 1")
    assert plan.hp_modulation_pct == 0  # nothing to command now: the pump runs on its own


def test_boost_now_at_negative_price() -> None:
    plan = _plan([-0.2, -0.1] + [1.1] * 46)
    assert plan.should_heat and plan.hp_modulation_pct == 100
    assert plan.optimization_reason.startswith("Doładowanie teraz – tania energia")
    assert "do 55 °C" in plan.optimization_reason
    assert plan.boost_target_t == 55


def test_boost_respects_heat_pump_limit_and_storage_max() -> None:
    plan = plan_boost(
        _cfg(hp_max_t=50), COP, now=NOW, current_t=35, slots=_slots([-0.5] * 6 + [1.2] * 42),
        outdoor_forecast={}, boost_t=70,
    )  # fmt: skip
    assert max(s.temperature_end for s in plan.steps) <= 50.5


def test_stale_prices_leave_the_heat_pump_alone() -> None:
    plan = _plan(_day(0.3) * 2, stale=True)
    assert plan.mode == "fallback" and not plan.should_heat and plan.strategy == "boost"


def test_heat_system_boost_strategy_and_shared_valve() -> None:
    slots = _slots(_day(0.2) * 2)
    dhw = _cfg(name="dhw", volume_l=200, min_t=40, max_t=60, target_t=45, building_kw_per_k=0.0)
    plan = plan_heat_system(
        {
            "buffer": StorageInput(_cfg(), 35.0, strategy="boost", boost_t=55),
            "dhw": StorageInput(dhw, 46.0, strategy="boost", boost_t=55),
        },
        COP,
        now=NOW,
        slots=slots,
        outdoor_forecast={},
        shared_hp=True,
    )
    b, d = plan.plans["buffer"].steps, plan.plans["dhw"].steps
    assert all(p.strategy == "boost" for p in plan.plans.values())
    # only one storage boosts at a time through the shared valve
    assert not any(x.heat_fraction > 0 and y.heat_fraction > 0 for x, y in zip(b, d, strict=False))
    assert plan.plans["buffer"].boost_hours or plan.plans["dhw"].boost_hours


# ------------------------------------------------------------- 7-day simulation
def _week(dips: list[float], flat: float | None = None) -> tuple[list[tuple[datetime, float]], dict[datetime, float]]:
    start = datetime(2026, 10, 5, 4, 0, tzinfo=UTC)  # Monday 06:00 local
    prices, outdoor = [], {}
    for day, dip in enumerate([*dips, dips[-1]]):  # + one day of look-ahead
        for i, p in enumerate(_day(dip) if flat is None else [flat] * 24):
            t = start + timedelta(days=day, hours=i)
            prices.append((t, p))
            outdoor[t] = 6.0 + 4.0 * math.sin((i - 8) / 24 * 2 * math.pi)
    return prices, outdoor


WEEK = [0.45, 0.3, 0.85, 0.2, 0.6, -0.1, 0.35]  # sunny, cloudy and a negative-price weekend


def test_week_simulation_boost_saves_and_keeps_comfort() -> None:
    prices, outdoor = _week(WEEK)
    res = compare(prices, outdoor, _cfg(), COP, start_t=35, boost_t=55, hours=24 * 7)
    auto, boost, full = res["auto"], res["boost"], res["full"]
    assert boost["end_heat_adjusted_cost_pln"] < auto["cost_pln"]  # boosting pays off
    assert full["end_heat_adjusted_cost_pln"] < auto["cost_pln"]
    for r in res.values():
        assert r["hours_below_min"] == 0, r
    assert 0 < boost["boost_hours"] <= 7 * 6  # only in the cheap windows
    assert auto["boost_hours"] == 0


def test_week_simulation_flat_prices_do_not_boost() -> None:
    prices, outdoor = _week([0.95] * 7, flat=0.95)
    sim = simulate("boost", prices, outdoor, _cfg(), COP, start_t=35, boost_t=55, hours=24 * 7)
    ref = simulate("auto", prices, outdoor, _cfg(), COP, start_t=35, boost_t=55, hours=24 * 7)
    assert sim.boost_hours == 0
    assert sim.cost == pytest.approx(ref.cost, rel=1e-6)


def test_simulation_uses_only_published_prices() -> None:
    """At 06:00 local only today is known; tomorrow's prices appear from 13:00."""
    from custom_components.pstryk_ai.optimization.simulation import _known_until

    last = datetime(2026, 10, 20, tzinfo=UTC)
    morning = datetime(2026, 10, 6, 4, 0, tzinfo=UTC)
    afternoon = datetime(2026, 10, 6, 11, 0, tzinfo=UTC)
    assert _known_until(morning, last) == datetime(2026, 10, 6, 22, 0, tzinfo=UTC)
    assert _known_until(afternoon, last) == datetime(2026, 10, 7, 22, 0, tzinfo=UTC)


# ------------------------------------------------------------- Home Assistant
@pytest.fixture
def _auto(enable_custom_integrations: None) -> None:
    pstryk_api._BUDGETS.clear()


@pytest.mark.usefixtures("_auto")
@pytest.mark.parametrize("expected_lingering_timers", [True])
async def test_strategy_select_and_boost_commands(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mqtt_mock
) -> None:
    aioclient_mock.get(PSTRYK_URL, side_effect=PstrykMock())
    _mock_public_apis(aioclient_mock)
    hass.states.async_set("sensor.bufor", "36.0")
    entry = _entry(boost_command_topic="loxone/pc/boost/set", boost_command_format="setpoint")
    await _setup(hass, entry)
    c = entry.runtime_data
    assert hass.states.get("select.pstryk_ai_heat_pump_strategy").state == "boost"  # default
    assert c.data.buffer.strategy == "boost"
    topics = {call.args[0] for call in mqtt_mock.async_publish.call_args_list}
    for t in ("optimizer/buffer/boost", "optimizer/buffer/boost_target", "optimizer/buffer/strategy"):
        assert f"pstryk_ai/home/{t}" in topics, t
    assert "loxone/pc/boost/set" not in topics  # advisory mode: no commands

    mqtt_mock.async_publish.reset_mock()
    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.pstryk_ai_advisory_mode"}, blocking=True)
    calls = {call.args[0]: call for call in mqtt_mock.async_publish.call_args_list}
    assert "loxone/pc/boost/set" in calls
    assert calls["loxone/pc/boost/set"].args[3] is False  # never retained
    payload = float(calls["loxone/pc/boost/set"].args[1])
    assert payload == 0 or payload == c.data.buffer.boost_target_t

    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": "select.pstryk_ai_heat_pump_strategy", "option": "full"}, blocking=True,
    )  # fmt: skip
    assert c.data.buffer.strategy == "full"
    assert c.controls["heat_pump_strategy"] == "full"
    assert await hass.config_entries.async_unload(entry.entry_id)
