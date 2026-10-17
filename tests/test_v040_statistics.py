"""v0.4.0: Pstryk daily totals imported into HA long-term statistics (recorder must start first)."""

from __future__ import annotations

from homeassistant.core import HomeAssistant

from custom_components.pstryk_ai.api import pstryk as pstryk_api

from .test_init import PSTRYK_URL, PstrykMock, _entry, _mock_public_apis, _setup


async def test_statistics_import(
    recorder_mock, hass: HomeAssistant, enable_custom_integrations, aioclient_mock
) -> None:
    from homeassistant.components.recorder.statistics import list_statistic_ids
    from pytest_homeassistant_custom_component.components.recorder.common import async_wait_recording_done

    pstryk_api._BUDGETS.clear()
    aioclient_mock.get(PSTRYK_URL, side_effect=PstrykMock())
    _mock_public_apis(aioclient_mock)
    entry = _entry(mqtt_enabled=False, pstryk_statistics_import=True)
    await _setup(hass, entry)
    await async_wait_recording_done(hass)
    ids = await hass.async_add_executor_job(list_statistic_ids, hass)
    found = {i["statistic_id"] for i in ids}
    assert {"pstryk_ai:import_cost", "pstryk_ai:energy_import", "pstryk_ai:sold_value"} <= found
    assert await hass.config_entries.async_unload(entry.entry_id)
