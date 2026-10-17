"""v0.2.0: configurable MQTT topics and the sidebar panel."""

from __future__ import annotations

from datetime import UTC, datetime
import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.pstryk_ai.api import pstryk as pstryk_api
from custom_components.pstryk_ai.config_flow import parse_topics
from custom_components.pstryk_ai.mqtt.discovery import discovery_messages
from custom_components.pstryk_ai.mqtt.publisher import MqttPublisher
from custom_components.pstryk_ai.mqtt.schemas import TOPICS, Message, resolve_topic, topic_field, validate_topic
from custom_components.pstryk_ai.outputs import build_messages
from custom_components.pstryk_ai.panel import FRONTEND_DIR, PANEL_URL_PATH, WEBCOMPONENT

from .test_init import PSTRYK_URL, PstrykMock, _entry, _mock_public_apis, _setup
from .test_mqtt_storage_e2e import _data, _scenario

ROOT = Path(__file__).parents[1]


@pytest.fixture(autouse=True)
def _auto(enable_custom_integrations: None) -> None:
    pstryk_api._BUDGETS.clear()


# ------------------------------------------------------------------ topics
def test_resolve_and_validate_topics() -> None:
    assert resolve_topic("pstryk_ai/home", "prices/current", None) == "pstryk_ai/home/prices/current"
    assert (
        resolve_topic("pstryk_ai/home/", "prices/current", {"prices/current": "cena/teraz"})
        == "pstryk_ai/home/cena/teraz"
    )
    assert resolve_topic("p", "prices/current", {"prices/current": "/loxone/cena"}) == "loxone/cena"
    assert resolve_topic("p", "prices/current", {"prices/current": ""}) is None
    assert validate_topic("") and validate_topic("a/b") and validate_topic("/abs/x")
    assert (
        not validate_topic("a/#")
        and not validate_topic("a/+/b")
        and not validate_topic("a//b")
        and not validate_topic("/")
    )


def test_every_published_topic_is_configurable() -> None:
    _, known, _, _, run, now, weather = _scenario()
    from custom_components.pstryk_ai.optimization.heat_pump import CopModel
    from custom_components.pstryk_ai.optimization.thermal_storage import BufferConfig, plan_buffer
    from custom_components.pstryk_ai.tariff import Tariff
    from custom_components.pstryk_ai.timeline import build_timeline

    tl = build_timeline(now, pstryk_buy=[], pstryk_sell=[], market_hourly=known, forecast=run, tariff=Tariff())
    plan = plan_buffer(BufferConfig(), CopModel(), now=now, current_t=40, slots=tl.buy, outdoor_forecast={})
    data = _data(now, tl, run, weather, plan)
    data.providers = {n: {"status": "ok"} for n in ("pstryk", "tge", "entsoe", "pse", "weather")}
    msgs = build_messages(data, price_threshold=0.5, evcc=True, include_sell=True)
    assert {m.topic for m in msgs} <= set(TOPICS)
    assert len({topic_field(t) for t in TOPICS}) == len(TOPICS)


def test_translation_generator_lists_all_topics() -> None:
    spec = importlib.util.spec_from_file_location("gen", ROOT / "scripts" / "gen_translations.py")
    gen = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gen)
    assert list(gen.TOPICS) == list(TOPICS)
    strings = json.loads((ROOT / "custom_components/pstryk_ai/strings.json").read_text())
    assert set(strings["options"]["step"]["mqtt_topics"]["data"]) == {topic_field(t) for t in TOPICS}


def test_parse_topics_rename_disable_duplicates() -> None:
    form = {topic_field(t): t for t in TOPICS}
    overrides, errors = parse_topics("p", form)
    assert overrides == {} and errors == {}
    form[topic_field("prices/current")] = "cena/teraz"
    form.pop(topic_field("evcc/prices"))  # cleared field -> disabled
    overrides, errors = parse_topics("p", form)
    assert errors == {}
    assert overrides == {"prices/current": "cena/teraz", "evcc/prices": ""}
    form[topic_field("prices/next")] = "cena/teraz"
    _, errors = parse_topics("p", form)
    assert errors == {topic_field("prices/next"): "duplicate_topic"}
    form[topic_field("prices/next")] = "a/#"
    _, errors = parse_topics("p", form)
    assert errors == {topic_field("prices/next"): "invalid_topic"}


async def test_publisher_applies_overrides(hass: HomeAssistant) -> None:
    pub = MqttPublisher(hass, "pstryk_ai/home", topics={"prices/current": "/loxone/cena", "prices/next": ""})
    hass.config.components.add("mqtt")
    with (
        patch("homeassistant.components.mqtt.is_connected", return_value=True),
        patch("homeassistant.components.mqtt.async_publish", autospec=True) as publish,
    ):
        sent = await pub.async_publish(
            [Message("prices/current", "1"), Message("prices/next", "2"), Message("status", "{}")], datetime.now(UTC)
        )
    assert sent == 2
    assert [c.args[1] for c in publish.call_args_list] == ["loxone/cena", "pstryk_ai/home/status"]


def test_discovery_follows_overrides() -> None:
    msgs = discovery_messages("p", "abcdef12", {"prices/current": "x/cena", "cheap/now": "", "availability": ""})
    cfgs = [json.loads(m[1]) for m in msgs]
    assert any(c["state_topic"] == "p/x/cena" for c in cfgs)
    assert not any(c["state_topic"].endswith("cheap/now") for c in cfgs)
    assert all("availability_topic" not in c for c in cfgs)


async def test_options_flow_mqtt_topics(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(PSTRYK_URL, side_effect=PstrykMock())
    _mock_public_apis(aioclient_mock)
    entry = _entry(mqtt_enabled=False)
    await _setup(hass, entry)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert "mqtt_topics" in result["menu_options"] and "panel" in result["menu_options"]
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "mqtt_topics"})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "mqtt_topics"
    form = {topic_field(t): t for t in TOPICS}
    form[topic_field("prices/next")] = "prices/current"
    result = await hass.config_entries.options.async_configure(result["flow_id"], form)
    assert result["errors"] == {topic_field("prices/next"): "duplicate_topic"}
    form[topic_field("prices/next")] = "/loxone/cena_nastepna"
    form.pop(topic_field("weather/solar"))
    with patch("custom_components.pstryk_ai.async_setup_entry", return_value=True):
        result = await hass.config_entries.options.async_configure(result["flow_id"], form)
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["mqtt_topics"] == {"prices/next": "/loxone/cena_nastepna", "weather/solar": ""}
    assert entry.options["market_provider"] == "pse_rce"


@pytest.mark.parametrize("expected_lingering_timers", [True])
async def test_renamed_topics_publish_and_clear_old_retained(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mqtt_mock, hass_storage
) -> None:
    aioclient_mock.get(PSTRYK_URL, side_effect=PstrykMock())
    _mock_public_apis(aioclient_mock)
    entry = _entry(mqtt_topics={"prices/current": "/loxone/cena", "evcc/prices": ""})
    entry.add_to_hass(hass)
    hass_storage[f"pstryk_ai.{entry.entry_id}.state"] = {
        "version": 1,
        "minor_version": 1,
        "key": f"pstryk_ai.{entry.entry_id}.state",
        "data": {"state": {"published_topics": ["pstryk_ai/home/prices/current", "pstryk_ai/home/old/topic"]}},
    }
    with (
        patch("custom_components.pstryk_ai.coordinator.PstrykAICoordinator.async_start_history_import"),
        patch("custom_components.pstryk_ai.coordinator.PstrykAICoordinator.async_retrain"),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    calls = {c.args[0]: c for c in mqtt_mock.async_publish.call_args_list}
    assert "loxone/cena" in calls
    assert "pstryk_ai/home/prices/current" in calls and calls["pstryk_ai/home/prices/current"].args[1] == ""
    assert calls["pstryk_ai/home/old/topic"].args[1] == ""  # stale retained message removed
    assert calls["pstryk_ai/home/old/topic"].args[3] is True
    assert "pstryk_ai/home/evcc/prices" not in calls
    assert await hass.config_entries.async_unload(entry.entry_id)


# ------------------------------------------------------------------- panel
def test_panel_asset_exists() -> None:
    js = (FRONTEND_DIR / f"{WEBCOMPONENT}.js").read_text(encoding="utf-8")
    assert f'customElements.define("{WEBCOMPONENT}"' in js
    for key in ("current_buy_price", "forecast_7d", "buffer_plan_reason", "cheapest_3h", "pstryk_api_status"):
        assert key in js


async def test_panel_registered_and_removed(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(PSTRYK_URL, side_effect=PstrykMock())
    _mock_public_apis(aioclient_mock)
    hass.config.components.update({"http", "frontend"})
    hass.http = type("H", (), {})()

    async def _static(paths):
        _static.paths = paths

    hass.http.async_register_static_paths = _static
    entry = _entry(mqtt_enabled=False)
    with (
        patch("homeassistant.components.panel_custom.async_register_panel") as register,
        patch("homeassistant.components.frontend.async_remove_panel") as remove,
    ):
        await _setup(hass, entry)
        register.assert_called_once()
        kwargs = register.call_args.kwargs
        assert kwargs["frontend_url_path"] == PANEL_URL_PATH and kwargs["webcomponent_name"] == WEBCOMPONENT
        assert kwargs["sidebar_title"] == "Pstryk AI"
        assert Path(_static.paths[0].path) == FRONTEND_DIR
        assert await hass.config_entries.async_unload(entry.entry_id)
        remove.assert_called_once()


async def test_panel_can_be_disabled(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(PSTRYK_URL, side_effect=PstrykMock())
    _mock_public_apis(aioclient_mock)
    hass.config.components.update({"http", "frontend"})
    entry = _entry(mqtt_enabled=False, show_panel=False)
    with patch("homeassistant.components.panel_custom.async_register_panel") as register:
        await _setup(hass, entry)
        register.assert_not_called()
        assert await hass.config_entries.async_unload(entry.entry_id)


async def test_monthly_balance_fetched_on_first_start(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    pm = PstrykMock()
    aioclient_mock.get(PSTRYK_URL, side_effect=pm)
    _mock_public_apis(aioclient_mock)
    entry = _entry(mqtt_enabled=False)
    await _setup(hass, entry)
    resolutions = [c.get("resolution") for c in pm.calls]
    assert resolutions == ["hour", "day"]
    assert hass.states.get("sensor.pstryk_ai_energy_import_month").state not in ("unknown", "unavailable")
    assert await hass.config_entries.async_unload(entry.entry_id)
