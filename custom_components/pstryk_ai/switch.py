"""Runtime switches (persisted in local storage, no reload required)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PstrykAIConfigEntry
from .coordinator import PstrykAICoordinator
from .entity import PstrykAIEntity

SWITCHES: tuple[SwitchEntityDescription, ...] = (
    SwitchEntityDescription(
        key="optimization_enabled", translation_key="optimization_enabled", entity_category=EntityCategory.CONFIG
    ),
    SwitchEntityDescription(
        key="buffer_enabled", translation_key="buffer_enabled", entity_category=EntityCategory.CONFIG
    ),
    SwitchEntityDescription(key="mqtt_enabled", translation_key="mqtt_enabled", entity_category=EntityCategory.CONFIG),
    SwitchEntityDescription(
        key="advisory_mode", translation_key="advisory_mode", entity_category=EntityCategory.CONFIG
    ),
)


# runtime switches for optional features – only created when the feature is configured
FEATURE_SWITCHES: tuple[tuple[SwitchEntityDescription, Callable[[Any], bool]], ...] = (
    (
        SwitchEntityDescription(
            key="dhw_enabled", translation_key="dhw_enabled", entity_category=EntityCategory.CONFIG
        ),
        lambda s: s.ext.dhw.enabled,
    ),
    (
        SwitchEntityDescription(
            key="buffer_heater_enabled", translation_key="buffer_heater_enabled", entity_category=EntityCategory.CONFIG
        ),
        lambda s: s.ext.buffer_heater.enabled,
    ),
    (
        SwitchEntityDescription(
            key="dhw_heater_enabled", translation_key="dhw_heater_enabled", entity_category=EntityCategory.CONFIG
        ),
        lambda s: s.ext.dhw.enabled and s.ext.dhw_heater.enabled,
    ),
    (
        SwitchEntityDescription(key="pv_enabled", translation_key="pv_enabled", entity_category=EntityCategory.CONFIG),
        lambda s: s.ext.pv_enabled,
    ),
    (
        SwitchEntityDescription(
            key="power_limit_enabled", translation_key="power_limit_enabled", entity_category=EntityCategory.CONFIG
        ),
        lambda s: s.ext.power_limit_enabled,
    ),
    (
        SwitchEntityDescription(
            key="optimize_all_in", translation_key="optimize_all_in", entity_category=EntityCategory.CONFIG
        ),
        lambda s: s.ext.distribution is not None or s.tariff.var_distribution_net > 0,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: PstrykAIConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    settings = entry.runtime_data.settings
    entities = [PstrykSwitch(entry.runtime_data, d) for d in SWITCHES]
    entities += [PstrykSwitch(entry.runtime_data, d) for d, ok in FEATURE_SWITCHES if ok(settings)]
    async_add_entities(entities)


class PstrykSwitch(PstrykAIEntity, SwitchEntity):
    _platform = "switch"

    def __init__(self, coordinator: PstrykAICoordinator, description: SwitchEntityDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.controls[self.entity_description.key])

    async def _set(self, value: bool) -> None:
        self.coordinator.set_control(self.entity_description.key, value)
        await self.coordinator.async_recalculate(reason=f"switch_{self.entity_description.key}", forecast=False)

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)
