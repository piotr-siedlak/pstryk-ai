"""Pstryk AI – Energy Intelligence & Optimization for Home Assistant."""

from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType
import voluptuous as vol

from .const import (
    DOMAIN,
    SERVICE_IMPORT_HISTORY,
    SERVICE_RECALCULATE_FORECAST,
    SERVICE_RECALCULATE_SCHEDULE,
    SERVICE_RETRAIN_MODEL,
    SERVICE_RUN_BACKTEST,
)
from .coordinator import PstrykAICoordinator
from .panel import async_register_panel, async_unregister_panel

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.BINARY_SENSOR,
    Platform.SWITCH,
    Platform.BUTTON,
    Platform.NUMBER,
    Platform.SELECT,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type PstrykAIConfigEntry = ConfigEntry[PstrykAICoordinator]

ATTR_ENTRY_ID = "config_entry_id"
ATTR_DAYS = "days"


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Register integration-wide services."""

    def _coordinators(call: ServiceCall) -> list[PstrykAICoordinator]:
        entry_id = call.data.get(ATTR_ENTRY_ID)
        entries = [
            e for e in hass.config_entries.async_loaded_entries(DOMAIN) if entry_id is None or e.entry_id == entry_id
        ]
        if not entries:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="no_entry")
        return [e.runtime_data for e in entries]

    async def recalc_forecast(call: ServiceCall) -> None:
        for coord in _coordinators(call):
            await coord.async_recalculate(reason="service_forecast", forecast=True)

    async def recalc_schedule(call: ServiceCall) -> None:
        for coord in _coordinators(call):
            await coord.async_recalculate(reason="service_schedule", forecast=False)

    async def retrain(call: ServiceCall) -> None:
        for coord in _coordinators(call):
            await coord.async_retrain()

    async def import_history(call: ServiceCall) -> None:
        for coord in _coordinators(call):
            coord.async_start_history_import(call.data.get(ATTR_DAYS))

    base = vol.Schema({vol.Optional(ATTR_ENTRY_ID): cv.string})
    hass.services.async_register(DOMAIN, SERVICE_RECALCULATE_FORECAST, recalc_forecast, schema=base)
    hass.services.async_register(DOMAIN, SERVICE_RECALCULATE_SCHEDULE, recalc_schedule, schema=base)
    hass.services.async_register(DOMAIN, SERVICE_RETRAIN_MODEL, retrain, schema=base)
    hass.services.async_register(DOMAIN, SERVICE_RUN_BACKTEST, retrain, schema=base)
    hass.services.async_register(
        DOMAIN,
        SERVICE_IMPORT_HISTORY,
        import_history,
        schema=base.extend({vol.Optional(ATTR_DAYS): vol.All(vol.Coerce(int), vol.Range(min=30, max=1100))}),
    )
    return True


async def async_setup_entry(hass: HomeAssistant, entry: PstrykAIConfigEntry) -> bool:
    coordinator = PstrykAICoordinator(hass, entry)
    await coordinator.async_initialize()
    await coordinator.async_start_inputs()
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    coordinator.async_start_schedule()
    if coordinator.settings.show_panel:
        await async_register_panel(hass)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    if coordinator.history_is_short():
        coordinator.async_start_history_import()
    elif not coordinator.forecaster.state.ridge and coordinator.settings.auto_retrain:
        entry.async_create_background_task(hass, coordinator.async_retrain(), f"{DOMAIN}_initial_train")
    return True


async def _async_options_updated(hass: HomeAssistant, entry: PstrykAIConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: PstrykAIConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    coordinator: PstrykAICoordinator | None = getattr(entry, "runtime_data", None)
    if unloaded and coordinator is not None:
        await coordinator.async_shutdown()
    if unloaded and not [e for e in hass.config_entries.async_loaded_entries(DOMAIN) if e.entry_id != entry.entry_id]:
        async_unregister_panel(hass)
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Delete local datasets when the integration is removed."""
    from .storage.cache import ProviderCache
    from .storage.history import HistoryStore

    await HistoryStore(hass, entry.entry_id).async_remove()
    await ProviderCache(hass, entry.entry_id).async_remove()
