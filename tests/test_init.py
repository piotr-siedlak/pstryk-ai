"""Home Assistant integration tests: config flow, setup, entities, MQTT, recovery."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
import json
from typing import Any
from unittest.mock import patch

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMocker,
    AiohttpClientMockResponse,
)

from custom_components.pstryk_ai.api import pstryk as pstryk_api
from custom_components.pstryk_ai.api.pstryk import local_day_bounds
from custom_components.pstryk_ai.const import CONF_API_KEY, DOMAIN
from custom_components.pstryk_ai.diagnostics import async_get_config_entry_diagnostics
from custom_components.pstryk_ai.models.price_slot import parse_iso

from .conftest import load_json, pstryk_frames, pstryk_payload

API_KEY = "sk-test-not-a-real-key"
PSTRYK_URL = "https://api.pstryk.pl/integrations/meter-data/unified-metrics/"


@pytest.fixture(autouse=True)
def _auto(enable_custom_integrations: None) -> None:
    pstryk_api._BUDGETS.clear()


@pytest.fixture(autouse=True)
async def _tz(hass: HomeAssistant) -> None:
    await hass.config.async_set_time_zone("Europe/Warsaw")
    hass.config.latitude, hass.config.longitude = 52.03, 21.05


class PstrykMock:
    """Answers unified-metrics requests for the requested window."""

    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []
        self.status = 200
        self.tomorrow = True

    async def __call__(self, method: str, url: Any, data: Any) -> AiohttpClientMockResponse:
        query = dict(url.query)
        self.calls.append(query)
        if self.status != 200:
            return AiohttpClientMockResponse(method, url, status=self.status)
        start = parse_iso(query["window_start"])
        end = parse_iso(query.get("window_end") or query["window_start"])
        hours = max(1, int((end - start).total_seconds() // 3600))
        frames = pstryk_frames(start, hours)
        if not self.tomorrow:
            _, today_end = local_day_bounds(dt_util.utcnow())
            for f in frames:
                if parse_iso(f["start"]) >= today_end:
                    f["metrics"]["pricing"]["price_gross"] = 0.5  # placeholder value
        if "pricing" not in query.get("metrics", ""):
            for f in frames:
                f["metrics"].pop("pricing", None)
        return AiohttpClientMockResponse(method, url, json=pstryk_payload(frames))


def _mock_public_apis(aioclient_mock: AiohttpClientMocker) -> None:
    pk5l = load_json("pse_pk5l.json")
    rce = load_json("pse_rce.json")
    aioclient_mock.get("https://api.raporty.pse.pl/api/pk5l-wp", json=pk5l)
    aioclient_mock.get("https://api.raporty.pse.pl/api/rce-pln", json=rce)

    async def weather(method: str, url: Any, data: Any) -> AiohttpClientMockResponse:
        lats = url.query["latitude"].split(",")
        now = dt_util.utcnow().replace(minute=0, second=0, microsecond=0) - timedelta(hours=24)
        times = [(now + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(24 * 8)]
        variables = url.query["hourly"].split(",")
        models = url.query.get("models", "").split(",") if "," in url.query.get("models", "") else [None]
        items = []
        for _ in lats:
            hourly: dict[str, Any] = {"time": times}
            for var in variables:
                for m in models:
                    key = f"{var}_{m}" if m else var
                    base = {"temperature_2m": 4.0, "wind_speed_100m": 7.0, "shortwave_radiation": 100.0}.get(var, 1.0)
                    hourly[key] = [base for _ in times]
            items.append({"hourly": hourly})
        return AiohttpClientMockResponse(method, url, json=items if len(lats) > 1 else items[0])

    aioclient_mock.get("https://api.open-meteo.com/v1/forecast", side_effect=weather)


def _entry(**options: Any) -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Pstryk AI",
        data={CONF_API_KEY: API_KEY},
        options={
            "market_provider": "pse_rce",
            "pse_enabled": True,
            "mqtt_enabled": True,
            "buffer_enabled": True,
            "buffer_temperature_entity": "sensor.bufor",
            "history_days": 60,
            "device_profiles": json.dumps([{"name": "Pralka", "power_kw": 2, "duration_h": 2, "consecutive": True}]),
            **options,
        },
        unique_id=pstryk_api.key_fingerprint(API_KEY),
    )


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    with (
        patch("custom_components.pstryk_ai.coordinator.PstrykAICoordinator.async_start_history_import"),
        patch("custom_components.pstryk_ai.coordinator.PstrykAICoordinator.async_retrain"),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


def _state(hass: HomeAssistant, domain: str, key: str):
    from homeassistant.helpers import entity_registry as er

    reg = er.async_get(hass)
    for ent in reg.entities.values():
        if ent.platform == DOMAIN and ent.unique_id.endswith(f"_{key}") and ent.domain == domain:
            return hass.states.get(ent.entity_id)
    raise AssertionError(f"entity {domain}.{key} not found")


# ---------------------------------------------------------------- config flow
async def test_config_flow_full_wizard(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    pm = PstrykMock()
    aioclient_mock.get(PSTRYK_URL, side_effect=pm)
    _mock_public_apis(aioclient_mock)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    assert result["type"] is FlowResultType.FORM and result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_API_KEY: f"  {API_KEY} "})
    assert result["step_id"] == "location"
    for step, data in (
        ("location", {"use_ha_location": True}),
        ("market", {"market_provider": "pse_rce", "pse_enabled": True, "tge_enabled": False, "eur_pln_rate": 4.3}),
        ("weather", {}),
        ("forecast", {}),
        ("optimization", {"device_profiles": "[]"}),
        ("buffer", {}),
        ("mqtt", {"mqtt_prefix": "pstryk_ai/home/", "mqtt_qos": "1"}),
    ):
        assert result["step_id"] == step
        result = await hass.config_entries.flow.async_configure(result["flow_id"], data)
    assert result["step_id"] == "validate"
    assert "pse: ok" in result["description_placeholders"]["results"]
    with patch("custom_components.pstryk_ai.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {CONF_API_KEY: API_KEY}
    assert result["options"]["mqtt_prefix"] == "pstryk_ai/home"
    assert result["options"]["mqtt_qos"] == 1
    assert len(pm.calls) == 1  # validation consumed exactly one request


async def test_config_flow_errors(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(PSTRYK_URL, status=401)
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_API_KEY: "bad"})
    assert result["errors"] == {"base": "invalid_auth"}
    aioclient_mock.clear_requests()
    aioclient_mock.get(PSTRYK_URL, status=429, headers={"Retry-After": "60"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_API_KEY: "bad2"})
    assert result["errors"] == {"base": "rate_limited"}


async def test_config_flow_validates_profiles(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(PSTRYK_URL, side_effect=PstrykMock())
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_API_KEY: API_KEY})
    for data in ({}, {"market_provider": "pse_rce"}, {}, {}):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], data)
    assert result["step_id"] == "optimization"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"device_profiles": "{not json"})
    assert result["errors"] == {"device_profiles": "invalid_profiles"}


# ---------------------------------------------------------------- setup
@pytest.mark.parametrize("expected_lingering_timers", [True])
async def test_setup_entities_and_mqtt(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, mqtt_mock) -> None:
    pm = PstrykMock()
    aioclient_mock.get(PSTRYK_URL, side_effect=pm)
    _mock_public_apis(aioclient_mock)
    hass.states.async_set("sensor.bufor", "38.5")
    entry = _entry()
    await _setup(hass, entry)

    price = _state(hass, "sensor", "current_buy_price")
    assert price is not None and float(price.state) > 0
    assert price.attributes["source"] == "ACTUAL_PSTRYK"
    assert price.attributes["confirmed"] is True
    assert _state(hass, "binary_sensor", "tomorrow_confirmed").state == "on"
    assert _state(hass, "sensor", "pstryk_api_status").state == "ok"
    assert _state(hass, "sensor", "buffer_target_temperature").state not in ("unknown", "unavailable")
    assert _state(hass, "sensor", "schedule_pralka").state not in ("unavailable",)
    assert float(_state(hass, "sensor", "energy_import_today").state) > 0
    # the 7-day forecast sensor mixes confirmed and predicted slots, clearly labelled
    series = _state(hass, "sensor", "forecast_7d").attributes["series"]
    assert "ACTUAL_PSTRYK" in series["source"]
    assert set(series["source"]) <= {
        "ACTUAL_PSTRYK",
        "PUBLISHED_TGE",
        "MODEL_FORECAST",
        "FALLBACK_FORECAST",
        "UNAVAILABLE",
    }
    # Pstryk request budget respected at startup
    assert len(pm.calls) <= 2

    topics = {c.args[0]: c for c in mqtt_mock.async_publish.call_args_list}
    for t in (
        "pstryk_ai/home/prices/current",
        "pstryk_ai/home/prices/today",
        "pstryk_ai/home/prices/tomorrow",
        "pstryk_ai/home/prices/forecast/7d",
        "pstryk_ai/home/prices/forecast/day/3",
        "pstryk_ai/home/cheap/now",
        "pstryk_ai/home/cheap/best_4h",
        "pstryk_ai/home/weather/forecast",
        "pstryk_ai/home/optimizer/buffer/should_heat",
        "pstryk_ai/home/optimizer/buffer/schedule",
        "pstryk_ai/home/status",
        "pstryk_ai/home/availability",
        "pstryk_ai/home/api/pstryk/status",
        "pstryk_ai/home/forecast/confidence",
    ):
        assert t in topics, t
    should_heat = topics["pstryk_ai/home/optimizer/buffer/should_heat"]
    assert should_heat.args[3] is False  # never retained
    today = json.loads(topics["pstryk_ai/home/prices/today"].args[1])
    assert today["schema"] == "pstryk_ai/v1"
    rec = today["data"][0]
    assert {"start", "end", "value", "unit", "source", "quality", "generated_at", "valid_until"} <= set(rec)
    # no secrets in any payload
    assert all(API_KEY not in str(c.args[1]) for c in mqtt_mock.async_publish.call_args_list)

    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert API_KEY not in json.dumps(diag, default=str)

    await hass.services.async_call(DOMAIN, "recalculate_forecast", {}, blocking=True)
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_tomorrow_placeholder_then_confirmed_event(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    pm = PstrykMock()
    pm.tomorrow = False
    aioclient_mock.get(PSTRYK_URL, side_effect=pm)
    _mock_public_apis(aioclient_mock)
    entry = _entry(mqtt_enabled=False)
    await _setup(hass, entry)
    assert _state(hass, "binary_sensor", "tomorrow_confirmed").state == "off"
    events: list = []
    hass.bus.async_listen(f"{DOMAIN}_prices_confirmed", events.append)
    pm.tomorrow = True
    coordinator = entry.runtime_data
    coordinator.pstryk.budget._calls.clear()  # simulate a new hour
    await coordinator.async_refresh_pstryk(prices_only=True)
    await coordinator.async_recalculate(reason="test", forecast=False)
    await hass.async_block_till_done()
    assert events
    assert _state(hass, "binary_sensor", "tomorrow_confirmed").state == "on"
    assert coordinator.history.snapshots  # forecast snapshot stored for later comparison
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_no_tomorrow_retry_before_noon(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker, freezer) -> None:
    freezer.move_to("2026-10-17T07:30:00Z")  # 09:30 local
    pm = PstrykMock()
    pm.tomorrow = False
    aioclient_mock.get(PSTRYK_URL, side_effect=pm)
    _mock_public_apis(aioclient_mock)
    entry = _entry(mqtt_enabled=False)
    await _setup(hass, entry)
    calls = len(pm.calls)
    entry.runtime_data.pstryk.budget._calls.clear()
    await entry.runtime_data.async_refresh_pstryk(prices_only=True)
    assert len(pm.calls) == calls  # prices are not published before ~13:00, no budget wasted
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_restart_recovery_keeps_confirmed_prices(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    pm = PstrykMock()
    aioclient_mock.get(PSTRYK_URL, side_effect=pm)
    _mock_public_apis(aioclient_mock)
    entry = _entry(mqtt_enabled=False)
    await _setup(hass, entry)
    before = _state(hass, "sensor", "current_buy_price").state
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    # API outage after restart
    pm.status = 503
    pstryk_api._BUDGETS.clear()
    with (
        patch("custom_components.pstryk_ai.coordinator.PstrykAICoordinator.async_start_history_import"),
        patch("custom_components.pstryk_ai.coordinator.PstrykAICoordinator.async_retrain"),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    after = _state(hass, "sensor", "current_buy_price")
    assert after.state == before
    assert after.attributes["source"] == "ACTUAL_PSTRYK"
    assert _state(hass, "sensor", "pstryk_api_status").state == "error"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_budget_persists_across_restart(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    pm = PstrykMock()
    aioclient_mock.get(PSTRYK_URL, side_effect=pm)
    _mock_public_apis(aioclient_mock)
    entry = _entry(mqtt_enabled=False)
    await _setup(hass, entry)
    c = entry.runtime_data
    for _ in range(5):
        await c.async_refresh_pstryk()
    assert len(pm.calls) <= 2  # hard local budget
    assert await hass.config_entries.async_unload(entry.entry_id)
    pstryk_api._BUDGETS.clear()  # process restart
    with (
        patch("custom_components.pstryk_ai.coordinator.PstrykAICoordinator.async_start_history_import"),
        patch("custom_components.pstryk_ai.coordinator.PstrykAICoordinator.async_retrain"),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    assert len(pm.calls) <= 2  # restored budget prevented new requests
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_auth_failure_starts_reauth(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(PSTRYK_URL, status=401)
    _mock_public_apis(aioclient_mock)
    entry = _entry(mqtt_enabled=False)
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    flows = hass.config_entries.flow.async_progress()
    assert any(f["context"]["source"] == "reauth" for f in flows)


async def test_mqtt_not_configured_is_reported(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(PSTRYK_URL, side_effect=PstrykMock())
    _mock_public_apis(aioclient_mock)
    entry = _entry()
    await _setup(hass, entry)
    assert _state(hass, "sensor", "mqtt_status").state == "not_configured"
    assert entry.runtime_data.publisher.skipped > 0
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_switch_number_select_controls(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(PSTRYK_URL, side_effect=PstrykMock())
    _mock_public_apis(aioclient_mock)
    hass.states.async_set("sensor.bufor", "40")
    entry = _entry(mqtt_enabled=False)
    await _setup(hass, entry)
    sw = _state(hass, "switch", "buffer_enabled")
    await hass.services.async_call("switch", "turn_off", {"entity_id": sw.entity_id}, blocking=True)
    assert entry.runtime_data.controls["buffer_enabled"] is False
    assert entry.runtime_data.data.buffer is None
    num = _state(hass, "number", "buffer_max_t")
    await hass.services.async_call("number", "set_value", {"entity_id": num.entity_id, "value": 60}, blocking=True)
    assert entry.runtime_data.controls["buffer_max_t"] == 60
    sel = _state(hass, "select", "forecast_model")
    await hass.services.async_call(
        "select", "select_option", {"entity_id": sel.entity_id, "option": "baseline"}, blocking=True
    )
    assert entry.runtime_data.forecaster.mode == "baseline"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_options_flow_menu(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(PSTRYK_URL, side_effect=PstrykMock())
    _mock_public_apis(aioclient_mock)
    entry = _entry(mqtt_enabled=False)
    await _setup(hass, entry)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "mqtt"})
    with patch("custom_components.pstryk_ai.async_setup_entry", return_value=True):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], {"mqtt_enabled": True, "mqtt_prefix": "dom/energia", "mqtt_qos": "0"}
        )
        await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options["mqtt_prefix"] == "dom/energia"
    assert entry.options["market_provider"] == "pse_rce"  # untouched options kept


def _noop(*_: Any) -> Callable[..., None]:
    return lambda *a, **k: None
