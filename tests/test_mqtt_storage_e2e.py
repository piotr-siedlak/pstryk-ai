"""MQTT payloads/publisher, storage persistence and the end-to-end simulated scenario."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from unittest.mock import AsyncMock, patch

from homeassistant.core import HomeAssistant
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.pstryk_ai.api import pstryk as pstryk_api
from custom_components.pstryk_ai.api.pstryk import parse_hourly
from custom_components.pstryk_ai.api.weather import WeatherHour
from custom_components.pstryk_ai.forecasting.features import FeatureContext, local_date
from custom_components.pstryk_ai.forecasting.model_manager import PriceForecaster
from custom_components.pstryk_ai.models.price_slot import MarketPoint, PriceSource
from custom_components.pstryk_ai.mqtt.discovery import discovery_messages
from custom_components.pstryk_ai.mqtt.publisher import MqttPublisher
from custom_components.pstryk_ai.mqtt.schemas import Message, compact_series, evcc_payload
from custom_components.pstryk_ai.optimization.heat_pump import CopModel
from custom_components.pstryk_ai.optimization.thermal_storage import BufferConfig, plan_buffer
from custom_components.pstryk_ai.outputs import PstrykAIData, build_messages, compute_windows
from custom_components.pstryk_ai.storage.history import HistoryStore
from custom_components.pstryk_ai.tariff import Tariff
from custom_components.pstryk_ai.timeline import build_timeline

from .conftest import local_midnight_utc, pstryk_frames, pstryk_payload, synthetic_market
from .test_init import PSTRYK_URL, PstrykMock, _entry, _mock_public_apis, _setup, _state


@pytest.fixture(autouse=True)
def _auto(enable_custom_integrations: None) -> None:
    pstryk_api._BUDGETS.clear()


def _scenario():
    """Synthetic but realistic state at 13:00 local on a working day."""
    hist = synthetic_market(datetime(2026, 3, 1, tzinfo=UTC), 24 * 230)
    now = local_midnight_utc(2026, 10, 14) + timedelta(hours=13)
    known = {k: v for k, v in hist.items() if local_date(k) <= local_date(now)}
    ctx = FeatureContext(known, {}, {})
    f = PriceForecaster()
    f.train(ctx, market_reference="synthetic", now=now, backtest_origins=15)
    run = f.forecast(ctx, now, sources=["synthetic"])
    weather = [WeatherHour(now + timedelta(hours=i), {"temperature_2m": 3.0 - (i % 24) / 6}) for i in range(168)]
    return hist, known, ctx, f, run, now, weather


def _data(now, timeline, run, weather, buffer=None) -> PstrykAIData:
    return PstrykAIData(
        now=now,
        timeline=timeline,
        forecast=run,
        pstryk=None,
        local_weather=weather,
        windows=compute_windows(timeline, now, cheap_hours=4, risk=0.3, speculative_h=48),
        buffer=buffer,
        providers={"pstryk": {"status": "ok"}},
        model_info={"mode": "auto"},
        flags={},
    )


def test_end_to_end_simulated_scenario() -> None:
    hist, known, _ctx, f, run, now, weather = _scenario()
    tariff = Tariff()
    # 1) 7-day forecast + weather
    assert len(run.points) >= 150
    outdoor = {w.start: w.get("temperature_2m") for w in weather}
    # 2) buffer plan on the predicted timeline
    tl = build_timeline(now, pstryk_buy=[], pstryk_sell=[], market_hourly=known, forecast=run, tariff=tariff)
    plan = plan_buffer(
        BufferConfig(max_horizon_h=72), CopModel(), now=now, current_t=38, slots=tl.buy, outdoor_forecast=outdoor
    )
    assert plan.steps
    # 3) publish plan to mocked MQTT (message list)
    msgs = build_messages(_data(now, tl, run, weather, plan), price_threshold=0.5, evcc=True, include_sell=False)
    topics = {m.topic: m for m in msgs}
    assert "optimizer/buffer/schedule" in topics and "evcc/prices" in topics
    assert topics["optimizer/buffer/should_heat"].retain is False
    assert topics["optimizer/buffer/should_heat"].expiry_s >= 60
    # 4) official Pstryk prices for tomorrow arrive
    tomorrow = local_date(now) + timedelta(days=1)
    t_start = local_midnight_utc(tomorrow.year, tomorrow.month, tomorrow.day)
    actual_market = {t: v for t, v in hist.items() if local_date(t) == tomorrow}
    frames = pstryk_frames(t_start, 24)
    for fr, (_t, v) in zip(frames, sorted(actual_market.items()), strict=True):
        fr["metrics"]["pricing"]["price_gross"] = round(tariff.energy_price(v), 4)
    snap = parse_hourly(pstryk_payload(frames), now)
    assert snap.tomorrow_confirmed
    # 5) recalculate: tomorrow is now confirmed, never shown as a forecast
    tl2 = build_timeline(
        now, pstryk_buy=snap.buy, pstryk_sell=snap.sell, market_hourly=known, forecast=run, tariff=tariff
    )
    day2 = [s for s in tl2.buy if local_date(s.start) == tomorrow]
    assert day2 and all(s.source is PriceSource.ACTUAL_PSTRYK for s in day2)
    plan2 = plan_buffer(
        BufferConfig(max_horizon_h=72), CopModel(), now=now, current_t=38, slots=tl2.buy, outdoor_forecast=outdoor
    )
    assert plan2.optimization_confidence >= plan.optimization_confidence - 1e-9
    # 6) compare forecast with actual prices
    predicted = {p.forecast_for: p.prediction_p50 for p in run.points if local_date(p.forecast_for) == tomorrow}
    errors = [abs(predicted[t] - v) for t, v in actual_market.items() if t in predicted]
    assert len(errors) >= 23
    mae = sum(errors) / len(errors)
    baseline_mae = f.state.backtest["metrics"]["baseline"]["1"]["mae"]
    assert mae < baseline_mae * 3  # sanity: forecast is in the right range, not a claim of accuracy


def test_mqtt_payload_sizes_and_schema() -> None:
    _, known, _, _, run, now, weather = _scenario()
    tl = build_timeline(now, pstryk_buy=[], pstryk_sell=[], market_hourly=known, forecast=run, tariff=Tariff())
    msgs = build_messages(_data(now, tl, run, weather), price_threshold=0.5, evcc=False, include_sell=False)
    for m in msgs:
        assert len(m.payload.encode()) < 64_000, m.topic  # separate day topics keep messages small
    seven = json.loads(next(m for m in msgs if m.topic == "prices/forecast/7d").payload)
    assert seven["schema"] == "pstryk_ai/v1" and seven["valid_until"]
    assert len(seven["data"]["start"]) == len(seven["data"]["value"]) == 168
    day1 = json.loads(next(m for m in msgs if m.topic == "prices/forecast/day/1").payload)
    assert all(r["source"] in ("MODEL_FORECAST", "FALLBACK_FORECAST", "PUBLISHED_TGE") for r in day1["data"])
    assert all("p10" in r for r in day1["data"] if r["source"].endswith("FORECAST"))
    assert compact_series(tl.buy[:3])["resolution"] == "PT60M"
    assert json.loads(evcc_payload(tl.buy[:2]))[0].keys() == {"start", "end", "value"}


def test_discovery_messages_are_limited() -> None:
    msgs = discovery_messages("pstryk_ai/home", "abcdef123456")
    assert 3 <= len(msgs) <= 10
    cfg = json.loads(msgs[0][1])
    assert cfg["state_topic"].startswith("pstryk_ai/home/")
    assert cfg["availability_topic"] == "pstryk_ai/home/availability"


async def test_publisher_skips_when_disconnected_and_recovers(hass: HomeAssistant) -> None:
    pub = MqttPublisher(hass, "pstryk_ai/home/")
    now = datetime.now(UTC)
    assert pub.status == "not_configured"
    assert await pub.async_publish([Message("a", "1")], now) == 0
    assert pub.skipped == 1
    hass.config.components.add("mqtt")
    with (
        patch("homeassistant.components.mqtt.is_connected", return_value=True),
        patch("homeassistant.components.mqtt.async_publish", new=AsyncMock()) as publish,
    ):
        sent = await pub.async_publish([Message("a", "1"), Message("b/c", "2", retain=False, expiry_s=120)], now)
    assert sent == 2
    assert publish.call_args_list[0].args[1] == "pstryk_ai/home/a"
    assert publish.call_args_list[1].kwargs["retain"] is False
    assert publish.call_args_list[1].kwargs["message_expiry_interval"] == 120
    assert pub.status in ("ok", "disconnected")


async def test_history_store_persistence_and_retention(hass: HomeAssistant) -> None:
    _, _known, _, _, run, _now, _ = _scenario()
    store = HistoryStore(hass, "entry1", history_days=400)
    await store.async_load()
    t0 = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
    pts = [MarketPoint(t0 - timedelta(hours=i), t0 - timedelta(hours=i - 1), 100.0 + i, "entsoe") for i in range(48)]
    pts.append(MarketPoint(t0 - timedelta(days=900), t0 - timedelta(days=900, hours=-1), 1.0, "entsoe"))
    store.add_market(pts)
    store.add_snapshot(run)
    store.add_pstryk_prices({t0 - timedelta(days=30): 1.0, t0: 0.5})
    await store.async_save_now()

    restored = HistoryStore(hass, "entry1", history_days=400)
    await restored.async_load()
    assert len(restored.market["entsoe"]) == 48  # 900-day-old point pruned
    assert len(restored.snapshots) == 1
    assert restored.snapshots[0].points[0].prediction_p50 == pytest.approx(run.points[0].prediction_p50, abs=1e-3)
    assert list(restored.pstryk_buy) == [t0]  # Pstryk data kept only 14 days
    # forecast snapshot comparison
    actual = {p.forecast_for: p.prediction_p50 + 10 for p in run.points[:30]}
    assert restored.evaluate_snapshots(actual, local_date) == 30
    assert restored.evaluate_snapshots(actual, local_date) == 0  # evaluated once
    assert all(v == pytest.approx(10, abs=1e-3) for v in restored.live_mae().values())


async def test_history_import_uses_public_sources_only(
    hass: HomeAssistant, aioclient_mock: AiohttpClientMocker
) -> None:
    pm = PstrykMock()
    aioclient_mock.get(PSTRYK_URL, side_effect=pm)
    _mock_public_apis(aioclient_mock)
    aioclient_mock.get(
        "https://historical-forecast-api.open-meteo.com/v1/forecast", json=[{"hourly": {"time": []}}] * 9
    )
    await hass.config.async_set_time_zone("Europe/Warsaw")
    entry = _entry(mqtt_enabled=False)
    await _setup(hass, entry)
    calls_before = len(pm.calls)
    c = entry.runtime_data
    with (
        patch("custom_components.pstryk_ai.coordinator.asyncio.sleep", new=AsyncMock()),
        patch.object(c, "async_retrain", new=AsyncMock()) as retrain,
    ):
        await c._import_history(60)
    assert c.import_status["state"] == "done"
    assert c.import_status["pse_pk5l"] > 0
    assert len(pm.calls) == calls_before  # no Pstryk backfill
    retrain.assert_awaited()
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_buffer_without_sensor_falls_back(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    aioclient_mock.get(PSTRYK_URL, side_effect=PstrykMock())
    _mock_public_apis(aioclient_mock)
    await hass.config.async_set_time_zone("Europe/Warsaw")
    entry = _entry(mqtt_enabled=False)  # sensor.bufor does not exist
    await _setup(hass, entry)
    should = _state(hass, "binary_sensor", "buffer_should_heat")
    assert should.state == "off"
    assert should.attributes["mode"] == "fallback"
    assert "lokalne" in should.attributes["reason"]
    assert await hass.config_entries.async_unload(entry.entry_id)
