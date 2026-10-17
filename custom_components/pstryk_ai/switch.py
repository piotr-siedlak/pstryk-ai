"""Runtime switches (persisted in local storage, no reload required)."""

from __future__ import annotations

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


async def async_setup_entry(
    hass: HomeAssistant, entry: PstrykAIConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities(PstrykSwitch(entry.runtime_data, d) for d in SWITCHES)


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
