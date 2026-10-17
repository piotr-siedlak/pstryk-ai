"""Number controls."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.const import EntityCategory, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PstrykAIConfigEntry
from .coordinator import PstrykAICoordinator
from .entity import PstrykAIEntity

NUMBERS: tuple[NumberEntityDescription, ...] = (
    NumberEntityDescription(
        key="buffer_max_t",
        translation_key="buffer_max_t",
        native_min_value=25,
        native_max_value=80,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    ),
    NumberEntityDescription(
        key="buffer_min_t",
        translation_key="buffer_min_t",
        native_min_value=10,
        native_max_value=70,
        native_step=0.5,
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    ),
    NumberEntityDescription(
        key="price_threshold",
        translation_key="price_threshold",
        native_min_value=-2,
        native_max_value=5,
        native_step=0.01,
        native_unit_of_measurement="PLN/kWh",
        mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG,
    ),
    NumberEntityDescription(
        key="cheap_hours",
        translation_key="cheap_hours",
        native_min_value=1,
        native_max_value=24,
        native_step=1,
        mode=NumberMode.SLIDER,
        entity_category=EntityCategory.CONFIG,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: PstrykAIConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities(PstrykNumber(entry.runtime_data, d) for d in NUMBERS)


class PstrykNumber(PstrykAIEntity, NumberEntity):
    _platform = "number"

    def __init__(self, coordinator: PstrykAICoordinator, description: NumberEntityDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> float:
        return float(self.coordinator.controls[self.entity_description.key])

    async def async_set_native_value(self, value: float) -> None:
        key = self.entity_description.key
        c = self.coordinator
        if key == "buffer_min_t" and value >= float(c.controls["buffer_max_t"]):
            value = float(c.controls["buffer_max_t"]) - 1
        if key == "buffer_max_t" and value <= float(c.controls["buffer_min_t"]):
            value = float(c.controls["buffer_min_t"]) + 1
        c.set_control(key, int(value) if key == "cheap_hours" else value)
        await c.async_recalculate(reason=f"number_{key}", forecast=False)
