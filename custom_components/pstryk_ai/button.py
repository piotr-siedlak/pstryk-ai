"""Buttons."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PstrykAIConfigEntry
from .coordinator import PstrykAICoordinator
from .entity import PstrykAIEntity

BUTTONS: tuple[ButtonEntityDescription, ...] = (
    ButtonEntityDescription(key="recalculate_forecast", translation_key="recalculate_forecast"),
    ButtonEntityDescription(key="recalculate_schedule", translation_key="recalculate_schedule"),
    ButtonEntityDescription(
        key="retrain_model", translation_key="retrain_model", entity_category=EntityCategory.CONFIG
    ),
    ButtonEntityDescription(
        key="import_history", translation_key="import_history", entity_category=EntityCategory.CONFIG
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: PstrykAIConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities(PstrykButton(entry.runtime_data, d) for d in BUTTONS)


class PstrykButton(PstrykAIEntity, ButtonEntity):
    _platform = "button"

    def __init__(self, coordinator: PstrykAICoordinator, description: ButtonEntityDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    async def async_press(self) -> None:
        key = self.entity_description.key
        c = self.coordinator
        if key == "recalculate_forecast":
            await c.async_recalculate(reason="button_forecast", forecast=True)
        elif key == "recalculate_schedule":
            await c.async_recalculate(reason="button_schedule", forecast=False)
        elif key == "retrain_model":
            self.hass.async_create_task(c.async_retrain())
        elif key == "import_history":
            c.async_start_history_import()
