"""Binary sensors."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity, BinarySensorEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PstrykAIConfigEntry
from .coordinator import PstrykAICoordinator
from .entity import PstrykAIEntity
from .optimization.cheapest_hours import classify
from .outputs import PstrykAIData


@dataclass(frozen=True, kw_only=True)
class PstrykBinaryDescription(BinarySensorEntityDescription):
    value_fn: Callable[[PstrykAIData, PstrykAICoordinator], bool | None]
    attrs_fn: Callable[[PstrykAIData, PstrykAICoordinator], dict[str, Any]] | None = None
    requires: Callable[[Any], bool] | None = None


def _flags(d: PstrykAIData, c: PstrykAICoordinator) -> dict[str, bool | None]:
    cur = d.current
    if cur is None:
        return {"cheap": None, "expensive": None, "below_absolute": None}
    return classify(cur, d.future(24), absolute_threshold=float(c.controls["price_threshold"]))


def _cheap(d: PstrykAIData, c: PstrykAICoordinator) -> bool | None:
    f = _flags(d, c)
    if f["cheap"] is None and f["below_absolute"] is None:
        return None
    return bool(f["cheap"]) or bool(f["below_absolute"])


BINARY: tuple[PstrykBinaryDescription, ...] = (
    PstrykBinaryDescription(
        key="cheap_now",
        translation_key="cheap_now",
        value_fn=_cheap,
        attrs_fn=lambda d, c: _flags(d, c) | {"threshold": c.controls["price_threshold"]},
    ),
    PstrykBinaryDescription(
        key="expensive_now", translation_key="expensive_now", value_fn=lambda d, c: _flags(d, c)["expensive"]
    ),
    PstrykBinaryDescription(
        key="pstryk_cheap_hour",
        translation_key="pstryk_cheap_hour",
        value_fn=lambda d, c: d.current.is_cheap if d.current else None,
        attrs_fn=lambda d, c: {"pstryk_is_expensive": d.current.is_expensive if d.current else None},
    ),
    PstrykBinaryDescription(
        key="tomorrow_confirmed",
        translation_key="tomorrow_confirmed",
        value_fn=lambda d, c: d.day_confirmed(1),
    ),
    PstrykBinaryDescription(
        key="buffer_should_heat",
        translation_key="buffer_should_heat",
        value_fn=lambda d, c: d.buffer.should_heat if d.buffer else None,
        attrs_fn=lambda d, c: (
            {
                "mode": d.buffer.mode,
                "reason": d.buffer.optimization_reason,
                "valid_until": d.buffer.valid_until.isoformat(),
            }
            if d.buffer
            else {}
        ),
    ),
)


def _plan_flags(p: Any) -> dict[str, Any]:
    if p is None:
        return {}
    return {"mode": p.mode, "reason": p.optimization_reason, "valid_until": p.valid_until.isoformat()}


EXTRA_BINARY: tuple[PstrykBinaryDescription, ...] = (
    PstrykBinaryDescription(
        key="dhw_should_heat",
        translation_key="dhw_should_heat",
        value_fn=lambda d, c: d.dhw.should_heat if d.dhw else None,
        attrs_fn=lambda d, c: _plan_flags(d.dhw),
        requires=lambda s: s.ext.dhw.enabled,
    ),
    PstrykBinaryDescription(
        key="buffer_heater_should_run",
        translation_key="buffer_heater_should_run",
        value_fn=lambda d, c: d.buffer.heater_should_run if d.buffer else None,
        attrs_fn=lambda d, c: {"power_kw": d.buffer.heater_power_kw} | _plan_flags(d.buffer) if d.buffer else {},
        requires=lambda s: s.ext.buffer_heater.enabled,
    ),
    PstrykBinaryDescription(
        key="dhw_heater_should_run",
        translation_key="dhw_heater_should_run",
        value_fn=lambda d, c: d.dhw.heater_should_run if d.dhw else None,
        attrs_fn=lambda d, c: {"power_kw": d.dhw.heater_power_kw} | _plan_flags(d.dhw) if d.dhw else {},
        requires=lambda s: s.ext.dhw.enabled and s.ext.dhw_heater.enabled,
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: PstrykAIConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    settings = entry.runtime_data.settings
    async_add_entities(
        PstrykBinary(entry.runtime_data, d)
        for d in (*BINARY, *EXTRA_BINARY)
        if d.requires is None or d.requires(settings)
    )


class PstrykBinary(PstrykAIEntity, BinarySensorEntity):
    _platform = "binary_sensor"
    entity_description: PstrykBinaryDescription

    def __init__(self, coordinator: PstrykAICoordinator, description: PstrykBinaryDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def is_on(self) -> bool | None:
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data, self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.coordinator.data is None or self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data, self.coordinator)
