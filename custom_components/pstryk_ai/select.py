"""Select controls."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity, SelectEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PstrykAIConfigEntry
from .const import BUFFER_STRATEGIES, FORECAST_MODELS
from .coordinator import PstrykAICoordinator
from .entity import PstrykAIEntity

SELECTS: tuple[SelectEntityDescription, ...] = (
    SelectEntityDescription(
        key="forecast_model",
        translation_key="forecast_model",
        options=FORECAST_MODELS,
        entity_category=EntityCategory.CONFIG,
    ),
    SelectEntityDescription(
        key="buffer_strategy",
        translation_key="buffer_strategy",
        options=BUFFER_STRATEGIES,
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: PstrykAIConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities(PstrykSelect(entry.runtime_data, d) for d in SELECTS)


class PstrykSelect(PstrykAIEntity, SelectEntity):
    _platform = "select"

    def __init__(self, coordinator: PstrykAICoordinator, description: SelectEntityDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def current_option(self) -> str:
        return str(self.coordinator.controls[self.entity_description.key])

    async def async_select_option(self, option: str) -> None:
        key = self.entity_description.key
        self.coordinator.set_control(key, option)
        await self.coordinator.async_recalculate(reason=f"select_{key}", forecast=key == "forecast_model")
