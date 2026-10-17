"""Base entity."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, NAME, VERSION
from .coordinator import PstrykAICoordinator


class PstrykAIEntity(CoordinatorEntity[PstrykAICoordinator]):
    _attr_has_entity_name = True
    _platform: str = ""

    def __init__(self, coordinator: PstrykAICoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{entry_id}_{key}"
        if self._platform:
            # language-independent entity IDs (names stay Polish via translations)
            self.entity_id = f"{self._platform}.pstryk_ai_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name=NAME,
            manufacturer=MANUFACTURER,
            model="Energy Intelligence & Optimization",
            sw_version=VERSION,
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://github.com/piotr-siedlak/pstryk-ai",
        )
