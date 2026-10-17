"""v0.3.0: temperatures read from exact MQTT topics (buffer, outdoor, devices)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.common import async_fire_mqtt_message, async_fire_time_changed
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.pstryk_ai.api import pstryk as pstryk_api
from custom_components.pstryk_ai.config_flow import validate_section
from custom_components.pstryk_ai.models.optimizer import DeviceProfile
from custom_components.pstryk_ai.models.price_slot import PriceSlot, PriceSource
from custom_components.pstryk_ai.mqtt.inputs import InputSpec, MqttInputs, parse_number
from custom_components.pstryk_ai.optimization.scheduler import schedule_device

from .test_init import PSTRYK_URL, PstrykMock, _entry, _mock_public_apis, _setup

BUFFER_TOPIC = "loxone/bufor/temperatura"


@pytest.fixture(autouse=True)
def _auto(enable_custom_integrations: None) -> None:
    pstryk_api._BUDGETS.clear()


@pytest.mark.parametrize(
    ("payload", "key", "expected"),
    [
        ("42.5", None, 42.5),
        ("42,5", None, 42.5),
        (b"40", None, 40.0),
        (" -3.2 ", None, -3.2),
        ('{"value": 41}', None, 41.0),
        ('{"temperature": "38,5", "unit": "C"}', None, 38.5),
        ('{"sensors": {"bufor": "39.5"}}', "sensors.bufor", 39.5),
        ('{"sensors": {"bufor": "39.5"}}', "sensors.cwu", None),
        ("45", None, 45.0),
        ("true", None, None),
        ("on", None, None),
        ("", None, None),
        ('{"other": 1}', None, None),
    ],
)
def test_parse_number(payload: str | bytes, key: str | None, expected: float | None) -> None:
    assert parse_number(payload, key) == expected


def test_inputs_freshness_and_range() -> None:
    clock = [datetime(2026, 10, 17, 10, tzinfo=UTC)]
    inputs = MqttInputs(
        None, [InputSpec("buffer", "t", None, 0, 100)], max_age=timedelta(minutes=30), now=lambda: clock[0]
    )  # type: ignore[arg-type]
    handler = inputs._handler(inputs.specs[0])

    class Msg:
        def __init__(self, payload: str) -> None:
            self.payload = payload

    handler(Msg("250"))  # out of plausible range
    assert inputs.value("buffer") is None and inputs.rejected["buffer"] == "250"
    handler(Msg("44.0"))
    assert inputs.value("buffer") == 44.0
    clock[0] += timedelta(minutes=31)
    assert inputs.value("buffer") is None
    assert inputs.status()["buffer"]["fresh"] is False


def test_scheduler_skips_device_at_target() -> None:
    now = datetime(2026, 10, 17, 10, tzinfo=UTC)
    slots = [
        PriceSlot(now + timedelta(hours=i), now + timedelta(hours=i + 1), 0.5 - i * 0.01, PriceSource.ACTUAL_PSTRYK)
        for i in range(24)
    ]
    prof = DeviceProfile("Bojler CWU", duration_h=2, target=55.0, temperature_topic="loxone/cwu/temp")
    done = schedule_device(prof, slots, now, current_value=56.0)
    assert done.feasible and done.slots == [] and "Cel osiągnięty" in done.reason
    assert done.to_dict()["current_value"] == 56.0 and done.to_dict()["target"] == 55.0
    todo = schedule_device(prof, slots, now, current_value=48.0)
    assert len(todo.slots) == 2
    unknown = schedule_device(prof, slots, now, current_value=None)
    assert len(unknown.slots) == 2 and "brak aktualnego odczytu MQTT" in unknown.reason


def test_profile_accepts_value_topic_alias() -> None:
    p = DeviceProfile.from_dict({"name": "EV", "value_topic": "evcc/soc", "value_key": "soc", "target": 80})
    assert p.temperature_topic == "evcc/soc" and p.temperature_key == "soc"


def test_validation_rejects_wildcard_topics() -> None:
    errors = validate_section(
        "buffer", {"buffer_top_topic": "loxone/#", "buffer_min_temperature": 30, "buffer_max_temperature": 50}
    )
    assert errors == {"buffer_top_topic": "invalid_input_topic"}
    profiles = json.dumps([{"name": "A", "temperature_topic": "a/+/b"}])
    assert validate_section("optimization", {"device_profiles": profiles}) == {"device_profiles": "invalid_input_topic"}
    ok = json.dumps([{"name": "A", "temperature_topic": "loxone/cwu", "target": 50}])
    assert validate_section("optimization", {"device_profiles": ok}) == {}


@pytest.mark.parametrize("expected_lingering_timers", [True])
async def test_buffer_and_device_temperatures_from_mqtt(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mqtt_mock, freezer
) -> None:
    aioclient_mock.get(PSTRYK_URL, side_effect=PstrykMock())
    _mock_public_apis(aioclient_mock)
    entry = _entry(
        buffer_temperature_entity="",
        buffer_temperature_topic=BUFFER_TOPIC,
        outdoor_temperature_topic="loxone/zewn",
        outdoor_temperature_json_key="value",
        mqtt_input_max_age_minutes=30,
        device_profiles=json.dumps(
            [
                {
                    "name": "Bojler CWU",
                    "power_kw": 3,
                    "duration_h": 2,
                    "target": 55,
                    "temperature_topic": "loxone/cwu/temp",
                }
            ]
        ),
    )
    await _setup(hass, entry)
    c = entry.runtime_data
    # before any message: no reading -> local control, no heating decision
    assert hass.states.get("binary_sensor.pstryk_ai_buffer_should_heat").attributes["mode"] == "fallback"
    assert hass.states.get("sensor.pstryk_ai_buffer_temperature").attributes["source"] == "mqtt_stale"

    async_fire_mqtt_message(hass, BUFFER_TOPIC, "38,5")
    async_fire_mqtt_message(hass, "loxone/zewn", '{"value": -2.0}')
    async_fire_mqtt_message(hass, "loxone/cwu/temp", "57")
    await hass.async_block_till_done()
    await c.async_recalculate(reason="test", forecast=False)
    await hass.async_block_till_done()

    temp = hass.states.get("sensor.pstryk_ai_buffer_temperature")
    assert float(temp.state) == 38.5 and temp.attributes["source"] == "mqtt"
    assert temp.attributes["mqtt"]["topic"] == BUFFER_TOPIC
    assert float(hass.states.get("sensor.pstryk_ai_outdoor_temperature").state) == -2.0
    heat = hass.states.get("binary_sensor.pstryk_ai_buffer_should_heat")
    assert heat.attributes["mode"] == "advisory"
    assert c.data.buffer.steps[0].temperature_start == pytest.approx(38.5)
    sched = hass.states.get("sensor.pstryk_ai_schedule_bojler_cwu")
    assert sched.attributes["hours"] == [] and "Cel osiągnięty" in sched.attributes["reason"]

    # device cools below target -> replanned automatically (deferred if a replan just ran)
    async_fire_mqtt_message(hass, "loxone/cwu/temp", "48")
    await hass.async_block_till_done(wait_background_tasks=True)
    freezer.tick(timedelta(minutes=5, seconds=1))
    async_fire_time_changed(hass)
    await hass.async_block_till_done(wait_background_tasks=True)
    assert len(hass.states.get("sensor.pstryk_ai_schedule_bojler_cwu").attributes["hours"]) == 2

    # readings become stale -> buffer falls back to local control
    freezer.tick(timedelta(minutes=26))
    await c.async_recalculate(reason="test", forecast=False)
    await hass.async_block_till_done()
    heat = hass.states.get("binary_sensor.pstryk_ai_buffer_should_heat")
    assert heat.state == "off" and heat.attributes["mode"] == "fallback"
    assert "MQTT" in heat.attributes["reason"]
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_mqtt_inputs_without_mqtt_raise_repair(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    from homeassistant.helpers import issue_registry as ir

    aioclient_mock.get(PSTRYK_URL, side_effect=PstrykMock())
    _mock_public_apis(aioclient_mock)
    entry = _entry(mqtt_enabled=False, buffer_temperature_topic=BUFFER_TOPIC)
    await _setup(hass, entry)
    assert ir.async_get(hass).async_get_issue("pstryk_ai", f"mqtt_inputs_{entry.entry_id}") is not None
    assert await hass.config_entries.async_unload(entry.entry_id)
