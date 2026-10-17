"""v0.4.0 Home Assistant tests: migration, all features on/off, commands, options, notifications, statistics."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.pstryk_ai.api import pstryk as pstryk_api
from custom_components.pstryk_ai.const import CONF_API_KEY, DOMAIN
from custom_components.pstryk_ai.notify import EVENT_NOTIFICATION

from .test_init import API_KEY, PSTRYK_URL, PstrykMock, _entry, _mock_public_apis, _setup

ALL_ON: dict[str, Any] = {
    "buffer_top_entity": "sensor.bufor_gora",
    "buffer_bottom_entity": "sensor.bufor_dol",
    "buffer_heater_enabled": True,
    "buffer_heater_steps_kw": "2,4",
    "buffer_heater_command_topic": "loxone/bufor/grzalka/set",
    "buffer_heater_command_format": "power_kw",
    "dhw_enabled": True,
    "dhw_top_entity": "sensor.cwu_gora",
    "dhw_bottom_entity": "sensor.cwu_dol",
    "dhw_heater_enabled": True,
    "dhw_heater_steps_kw": "2",
    "dhw_heater_command_topic": "loxone/cwu/grzalka/set",
    "dhw_valve_command_topic": "loxone/pc/zawor/set",
    "legionella_enabled": True,
    "distribution_tariff": "G12",
    "distribution_rate_peak": 0.35,
    "distribution_rate_offpeak": 0.08,
    "optimize_on_all_in_price": True,
    "pv_enabled": True,
    "pv_kwp": 6,
    "prosumer": True,
    "power_limit_enabled": True,
    "power_limit_kw": 9,
    "heat_pump_power_entity": "sensor.pc_moc",
    "learn_losses": True,
    "notify_tomorrow_prices": True,
    "notify_negative_prices": True,
    "mqtt_heartbeat": True,
}


@pytest.fixture(autouse=True)
def _auto(enable_custom_integrations: None) -> None:
    pstryk_api._BUDGETS.clear()


def _sensors(hass: HomeAssistant) -> None:
    for eid, v in (
        ("sensor.bufor_gora", "44.0"),
        ("sensor.bufor_dol", "33.0"),
        ("sensor.cwu_gora", "47.5"),
        ("sensor.cwu_dol", "38.0"),
        ("sensor.pc_moc", "1.8"),
    ):
        hass.states.async_set(eid, v)


async def test_migration_moves_buffer_sensor_to_top(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(PSTRYK_URL, side_effect=PstrykMock())
    _mock_public_apis(aioclient_mock)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={CONF_API_KEY: API_KEY},
        options={
            "market_provider": "pse_rce",
            "mqtt_enabled": False,
            "buffer_enabled": True,
            "buffer_temperature_topic": "loxone/bufor",
            "buffer_temperature_json_key": "value",
            "buffer_temperature_entity": "sensor.stary",
        },
        version=1,
        minor_version=1,
        unique_id=pstryk_api.key_fingerprint(API_KEY),
    )
    await _setup(hass, entry)
    assert entry.minor_version == 2
    assert entry.options["buffer_top_topic"] == "loxone/bufor"
    assert entry.options["buffer_top_json_key"] == "value"
    assert entry.options["buffer_top_entity"] == "sensor.stary"
    assert "buffer_temperature_topic" not in entry.options
    assert entry.runtime_data.settings.buffer_temp_topic == "loxone/bufor"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_features_off_create_no_extra_entities(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(PSTRYK_URL, side_effect=PstrykMock())
    _mock_public_apis(aioclient_mock)
    entry = _entry(mqtt_enabled=False, pstryk_spends=False)
    await _setup(hass, entry)
    for eid in (
        "sensor.pstryk_ai_dhw_soc",
        "binary_sensor.pstryk_ai_dhw_should_heat",
        "switch.pstryk_ai_dhw_enabled",
        "sensor.pstryk_ai_valve_position",
        "sensor.pstryk_ai_distribution_zone",
        "sensor.pstryk_ai_pv_production_today",
        "sensor.pstryk_ai_cost_yesterday",
        "binary_sensor.pstryk_ai_buffer_heater_should_run",
    ):
        assert hass.states.get(eid) is None, eid
    assert entry.runtime_data.data.dhw is None and entry.runtime_data.data.spends is None
    assert await hass.config_entries.async_unload(entry.entry_id)


@pytest.mark.parametrize("expected_lingering_timers", [True])
async def test_all_features_on(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mqtt_mock) -> None:
    pm = PstrykMock()
    aioclient_mock.get(PSTRYK_URL, side_effect=pm)
    _mock_public_apis(aioclient_mock)
    _sensors(hass)
    entry = _entry(**ALL_ON)
    await _setup(hass, entry)
    c = entry.runtime_data
    # entities exist and carry values
    assert float(hass.states.get("sensor.pstryk_ai_buffer_bottom_temperature").state) == 33.0
    assert float(hass.states.get("sensor.pstryk_ai_buffer_temperature").state) == 44.0
    assert hass.states.get("sensor.pstryk_ai_buffer_soc").state not in ("unknown", "unavailable")
    assert float(hass.states.get("sensor.pstryk_ai_dhw_top_temperature").state) == 47.5
    assert hass.states.get("binary_sensor.pstryk_ai_dhw_should_heat").state in ("on", "off")
    assert hass.states.get("sensor.pstryk_ai_valve_position").state in ("buffer", "dhw", "idle")
    assert hass.states.get("sensor.pstryk_ai_distribution_zone").state in ("peak", "offpeak")
    assert hass.states.get("sensor.pstryk_ai_pv_production_today") is not None
    assert hass.states.get("switch.pstryk_ai_dhw_enabled").state == "on"
    assert hass.states.get("switch.pstryk_ai_optimize_all_in").state == "on"
    assert float(hass.states.get("sensor.pstryk_ai_cost_yesterday").state) > 0
    assert hass.states.get("sensor.pstryk_ai_projected_month_cost").state not in ("unknown", "unavailable")
    # valve exclusive in the plan
    b, d = c.data.buffer.steps, c.data.dhw.steps
    assert not any(x.hp_kwh > 0 and y.hp_kwh > 0 for x, y in zip(b, d, strict=False))
    # Pstryk budget still respected (hourly + daily at startup)
    assert len(pm.calls) <= 2

    topics = {call.args[0] for call in mqtt_mock.async_publish.call_args_list}
    for t in (
        "pstryk_ai/home/optimizer/dhw/should_heat",
        "pstryk_ai/home/optimizer/dhw/schedule",
        "pstryk_ai/home/optimizer/buffer/heater/should_run",
        "pstryk_ai/home/optimizer/buffer/soc",
        "pstryk_ai/home/optimizer/valve",
        "pstryk_ai/home/spends/summary",
        "pstryk_ai/home/spends/daily",
    ):
        assert t in topics, t
    # advisory mode (default): no commands to the user's actuators
    assert not {"loxone/bufor/grzalka/set", "loxone/cwu/grzalka/set", "loxone/pc/zawor/set"} & topics

    # switch to control mode -> commands are published, never retained
    mqtt_mock.async_publish.reset_mock()
    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.pstryk_ai_advisory_mode"}, blocking=True)
    calls = {call.args[0]: call for call in mqtt_mock.async_publish.call_args_list}
    for t in ("loxone/bufor/grzalka/set", "loxone/cwu/grzalka/set", "loxone/pc/zawor/set"):
        assert t in calls, t
        assert calls[t].args[3] is False
    assert calls["loxone/pc/zawor/set"].args[1] in ("buffer", "dhw", "idle")
    float(calls["loxone/bufor/grzalka/set"].args[1])  # power format -> number

    # turning a feature off at runtime removes its plan
    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.pstryk_ai_dhw_enabled"}, blocking=True)
    assert c.data.dhw is None
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_feature_cannot_be_enabled_when_off_in_options(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, hass_storage
) -> None:
    aioclient_mock.get(PSTRYK_URL, side_effect=PstrykMock())
    _mock_public_apis(aioclient_mock)
    entry = _entry(mqtt_enabled=False)
    entry.add_to_hass(hass)
    hass_storage[f"pstryk_ai.{entry.entry_id}.state"] = {
        "version": 1,
        "minor_version": 1,
        "key": f"pstryk_ai.{entry.entry_id}.state",
        "data": {"state": {"controls": {"dhw_enabled": True, "pv_enabled": True}}},
    }
    with (
        patch("custom_components.pstryk_ai.coordinator.PstrykAICoordinator.async_start_history_import"),
        patch("custom_components.pstryk_ai.coordinator.PstrykAICoordinator.async_retrain"),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert entry.runtime_data.controls["dhw_enabled"] is False
    assert entry.runtime_data.controls["pv_enabled"] is False
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_new_option_steps(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(PSTRYK_URL, side_effect=PstrykMock())
    _mock_public_apis(aioclient_mock)
    entry = _entry(mqtt_enabled=False)
    await _setup(hass, entry)

    async def open_step(step: str):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        return await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": step})

    result = await open_step("dhw")
    assert result["step_id"] == "dhw"
    bad = {
        "dhw_enabled": True,
        "dhw_ready_times": "rano",
        "dhw_min_temperature": 40,
        "dhw_max_temperature": 60,
        "dhw_capacity_liters": 200,
        "dhw_target_temperature": 50,
        "dhw_ready_temperature": 45,
        "dhw_liters_per_day": 150,
        "dhw_losses": 0.002,
        "dhw_heat_pump_mode": "valve",
        "dhw_priority": True,
        "legionella_enabled": False,
        "legionella_temperature": 60,
        "legionella_interval_days": 7,
        "dhw_top_topic": "loxone/cwu/#",
    }
    result = await hass.config_entries.options.async_configure(result["flow_id"], bad)
    assert result["errors"] == {"dhw_ready_times": "invalid_times", "dhw_top_topic": "invalid_input_topic"}

    result = await open_step("buffer_heater")
    form = {
        "buffer_heater_enabled": True,
        "buffer_heater_kind": "electric",
        "buffer_heater_steps_kw": "abc",
        "buffer_heater_efficiency": 1.0,
        "buffer_heater_fuel_price": 0.3,
        "buffer_heater_command_format": "binary",
    }
    result = await hass.config_entries.options.async_configure(result["flow_id"], form)
    assert result["errors"] == {"buffer_heater_steps_kw": "invalid_steps"}
    form["buffer_heater_steps_kw"] = "2,4"
    form["buffer_heater_command_topic"] = "loxone/bufor/grzalka"
    with patch("custom_components.pstryk_ai.async_setup_entry", return_value=True):
        result = await hass.config_entries.options.async_configure(result["flow_id"], form)
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["buffer_heater_steps_kw"] == "2,4"
    assert entry.options["buffer_heater_max_temperature"] == ""

    for step, data, err in (
        (
            "tariff",
            {
                "distribution_tariff": "G12",
                "distribution_rate_peak": 0.3,
                "distribution_rate_offpeak": 0.1,
                "distribution_rate_peak2": 0,
                "distribution_weekend_offpeak": False,
                "optimize_on_all_in_price": True,
                "distribution_offpeak_hours": "noc",
            },
            {"distribution_offpeak_hours": "invalid_hours"},
        ),
        (
            "notifications",
            {
                "notify_tomorrow_prices": True,
                "notify_negative_prices": False,
                "notify_local_control": False,
                "notify_stale_data": False,
                "mqtt_heartbeat": False,
                "notify_service": "telefon",
            },
            {"notify_service": "invalid_notify_service"},
        ),
    ):
        result = await open_step(step)
        result = await hass.config_entries.options.async_configure(result["flow_id"], data)
        assert result["errors"] == err, step
    for step in ("power", "pv", "learning", "dhw_heater"):
        result = await open_step(step)
        assert result["type"] is FlowResultType.FORM and result["step_id"] == step


async def test_notifications_on_confirmed_prices(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    pm = PstrykMock()
    aioclient_mock.get(PSTRYK_URL, side_effect=pm)
    _mock_public_apis(aioclient_mock)
    events: list = []
    hass.bus.async_listen(EVENT_NOTIFICATION, events.append)
    entry = _entry(mqtt_enabled=False, notify_tomorrow_prices=True, notify_negative_prices=True)
    await _setup(hass, entry)
    await hass.async_block_till_done()
    kinds = [e.data["kind"] for e in events]
    assert "tomorrow_prices" in kinds
    assert hass.states.get("persistent_notification.pstryk_ai_tomorrow_prices") is not None or kinds
    # dedup: recalculating does not repeat the same day's summary
    await entry.runtime_data.async_recalculate(reason="again", forecast=False)
    await hass.async_block_till_done()
    assert [e.data["kind"] for e in events].count("tomorrow_prices") == 1
    assert await hass.config_entries.async_unload(entry.entry_id)


def test_options_cover_all_heat_topics() -> None:
    from custom_components.pstryk_ai.mqtt.schemas import TOPICS

    for t in ("optimizer/dhw/should_heat", "optimizer/valve", "spends/summary", "heartbeat"):
        assert t in TOPICS
    assert json.dumps(ALL_ON)
