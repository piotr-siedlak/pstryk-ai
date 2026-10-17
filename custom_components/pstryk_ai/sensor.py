"""Sensors (names are Polish via translation keys)."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfEnergy, UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import PstrykAIConfigEntry
from .api.pstryk import local_day_bounds
from .coordinator import PstrykAICoordinator
from .entity import PstrykAIEntity
from .models.price_slot import PriceSlot, PriceSource, iso
from .mqtt.schemas import compact_series
from .outputs import PstrykAIData

PRICE_UNIT = "PLN/kWh"
CURRENCY = "PLN"


@dataclass(frozen=True, kw_only=True)
class PstrykSensorDescription(SensorEntityDescription):
    value_fn: Callable[[PstrykAIData, PstrykAICoordinator], Any]
    attrs_fn: Callable[[PstrykAIData, PstrykAICoordinator], dict[str, Any]] | None = None


def _slot_attrs(slot: PriceSlot | None) -> dict[str, Any]:
    if slot is None:
        return {}
    attrs: dict[str, Any] = {
        "source": slot.source.value,
        "quality": slot.quality,
        "start": iso(slot.start),
        "end": iso(slot.end),
        "confirmed": slot.source is PriceSource.ACTUAL_PSTRYK,
    }
    if slot.source.is_forecast:
        attrs.update(
            {"p10": slot.p10, "p50": slot.p50, "p90": slot.p90, "confidence": slot.confidence, "model": slot.model_name}
        )
    if slot.is_cheap is not None:
        attrs["pstryk_is_cheap"] = slot.is_cheap
        attrs["pstryk_is_expensive"] = slot.is_expensive
    if "market_pln_mwh" in slot.meta:
        attrs["market_pln_mwh"] = slot.meta["market_pln_mwh"]
    return attrs


def _value(slot: PriceSlot | None) -> float | None:
    return None if slot is None or slot.value is None else round(slot.value, 4)


def _day_attrs(data: PstrykAIData, offset: int) -> dict[str, Any]:
    slots = data.day(offset)
    return {
        "confirmed": data.day_confirmed(offset),
        "sources": sorted({s.source.value for s in slots}),
        "prices": [{"start": iso(s.start), "value": _value(s), "source": s.source.value} for s in slots],
    }


def _extreme(data: PstrykAIData, offset: int, cheapest: bool) -> PriceSlot | None:
    slots = [s for s in data.day(offset) if s.value is not None]
    if not slots:
        return None
    return (min if cheapest else max)(slots, key=lambda s: s.value)  # type: ignore[arg-type,return-value]


def _at(data: PstrykAIData, hours: int) -> PriceSlot | None:
    return data.timeline.at(data.now + timedelta(hours=hours))


def _window_start(key: str) -> Callable[[PstrykAIData, PstrykAICoordinator], datetime | None]:
    return lambda d, c: d.windows[key].start if d.windows.get(key) else None


def _window_attrs(key: str) -> Callable[[PstrykAIData, PstrykAICoordinator], dict[str, Any]]:
    return lambda d, c: d.windows[key].to_dict() if d.windows.get(key) else {}


def _today_frames(data: PstrykAIData):
    start, end = local_day_bounds(data.now)
    return [f for f in (data.pstryk.hourly if data.pstryk else []) if start <= f.start < end]


def _sum(frames, attr: str) -> float | None:
    vals = [getattr(f, attr) for f in frames if getattr(f, attr) is not None]
    return round(sum(vals), 3) if vals else None


def _month(data: PstrykAIData, attr: str) -> float | None:
    return _sum(data.daily, attr)


def _accuracy(data: PstrykAIData, coord: PstrykAICoordinator) -> float | None:
    live = coord.history.live_mae()
    if live.get("1") is not None:
        return live["1"]
    bt = data.model_info.get("backtest_mae") or {}
    model = "ensemble" if bt.get("ensemble") else "baseline"
    return (bt.get(model) or {}).get("1")


def _buffer(attr: str) -> Callable[[PstrykAIData, PstrykAICoordinator], Any]:
    def fn(d: PstrykAIData, c: PstrykAICoordinator) -> Any:
        if d.buffer is None:
            return None
        value = getattr(d.buffer, attr)
        return round(value, 2) if isinstance(value, float) else value

    return fn


def _status(name: str) -> Callable[[PstrykAIData, PstrykAICoordinator], str]:
    return lambda d, c: c.status[name].status


STATUS_OPTIONS = ["ok", "pending", "error", "auth_error", "rate_limited", "disabled", "disconnected", "not_configured"]


def _market_status(d: PstrykAIData, c: PstrykAICoordinator) -> str:
    for name in ("tge", "entsoe", "pse"):
        st = c.status[name]
        if st.enabled:
            return st.status
    return "disabled"


SENSORS: tuple[PstrykSensorDescription, ...] = (
    PstrykSensorDescription(
        key="current_buy_price",
        translation_key="current_buy_price",
        native_unit_of_measurement=PRICE_UNIT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        value_fn=lambda d, c: _value(d.current),
        attrs_fn=lambda d, c: _slot_attrs(d.current),
    ),
    PstrykSensorDescription(
        key="current_sell_price",
        translation_key="current_sell_price",
        native_unit_of_measurement=PRICE_UNIT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        value_fn=lambda d, c: _value(d.current_sell()),
        attrs_fn=lambda d, c: _slot_attrs(d.current_sell()),
    ),
    PstrykSensorDescription(
        key="current_all_in_price",
        translation_key="current_all_in_price",
        native_unit_of_measurement=PRICE_UNIT,
        state_class=SensorStateClass.MEASUREMENT,
        suggested_display_precision=3,
        value_fn=lambda d, c: (
            None if _value(d.current) is None else round(c.settings.tariff.all_in(d.current.value), 4)
        ),  # type: ignore[union-attr,arg-type]
        attrs_fn=lambda d, c: {
            "distribution_gross": round(c.settings.tariff.distribution_gross(), 4),
            "pstryk_includes_distribution": c.settings.tariff.pstryk_includes_distribution,
            "note": "Szacunek: cena energii + zmienna opłata dystrybucyjna",
        },
    ),
    PstrykSensorDescription(
        key="next_hour_price",
        translation_key="next_hour_price",
        native_unit_of_measurement=PRICE_UNIT,
        suggested_display_precision=3,
        value_fn=lambda d, c: _value(d.next),
        attrs_fn=lambda d, c: _slot_attrs(d.next),
    ),
    PstrykSensorDescription(
        key="average_today",
        translation_key="average_today",
        native_unit_of_measurement=PRICE_UNIT,
        suggested_display_precision=3,
        value_fn=lambda d, c: _r(d.average(d.day(0))),
        attrs_fn=lambda d, c: _day_attrs(d, 0),
    ),
    PstrykSensorDescription(
        key="average_tomorrow",
        translation_key="average_tomorrow",
        native_unit_of_measurement=PRICE_UNIT,
        suggested_display_precision=3,
        value_fn=lambda d, c: _r(d.average(d.day(1))),
        attrs_fn=lambda d, c: _day_attrs(d, 1),
    ),
    PstrykSensorDescription(
        key="cheapest_hour_today",
        translation_key="cheapest_hour_today",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d, c: s.start if (s := _extreme(d, 0, True)) else None,
        attrs_fn=lambda d, c: _slot_attrs(_extreme(d, 0, True)) | {"price": _value(_extreme(d, 0, True))},
    ),
    PstrykSensorDescription(
        key="cheapest_hour_tomorrow",
        translation_key="cheapest_hour_tomorrow",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=lambda d, c: s.start if (s := _extreme(d, 1, True)) else None,
        attrs_fn=lambda d, c: _slot_attrs(_extreme(d, 1, True)) | {"price": _value(_extreme(d, 1, True))},
    ),
    PstrykSensorDescription(
        key="cheapest_3h",
        translation_key="cheapest_3h",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_window_start("best_3h_24h"),
        attrs_fn=_window_attrs("best_3h_24h"),
    ),
    PstrykSensorDescription(
        key="cheapest_6h",
        translation_key="cheapest_6h",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_window_start("best_6h_24h"),
        attrs_fn=_window_attrs("best_6h_24h"),
    ),
    PstrykSensorDescription(
        key="cheapest_n_hours",
        translation_key="cheapest_n_hours",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_window_start("cheapest_n_24h"),
        attrs_fn=_window_attrs("cheapest_n_24h"),
    ),
    PstrykSensorDescription(
        key="most_expensive_hour",
        translation_key="most_expensive_hour",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_window_start("most_expensive_1h_24h"),
        attrs_fn=_window_attrs("most_expensive_1h_24h"),
    ),
    *(
        PstrykSensorDescription(
            key=f"forecast_{h}h",
            translation_key=f"forecast_{h}h",
            native_unit_of_measurement=PRICE_UNIT,
            suggested_display_precision=3,
            value_fn=(lambda hh: lambda d, c: _value(_at(d, hh)))(h),
            attrs_fn=(lambda hh: lambda d, c: _slot_attrs(_at(d, hh)))(h),
        )
        for h in (24, 48, 72)
    ),
    PstrykSensorDescription(
        key="forecast_7d",
        translation_key="forecast_7d",
        native_unit_of_measurement=PRICE_UNIT,
        suggested_display_precision=3,
        value_fn=lambda d, c: _value(_at(d, 167)),
        attrs_fn=lambda d, c: {"series": compact_series(d.future(168))},
    ),
    PstrykSensorDescription(
        key="average_7d",
        translation_key="average_7d",
        native_unit_of_measurement=PRICE_UNIT,
        suggested_display_precision=3,
        value_fn=lambda d, c: _r(d.average(d.future(168))),
        attrs_fn=lambda d, c: {
            "confirmed_hours": sum(1 for s in d.future(168) if s.source is PriceSource.ACTUAL_PSTRYK),
            "forecast_hours": sum(1 for s in d.future(168) if s.source.is_forecast),
            "unavailable_hours": sum(1 for s in d.future(168) if s.source is PriceSource.UNAVAILABLE),
        },
    ),
    PstrykSensorDescription(
        key="cheap_probability",
        translation_key="cheap_probability",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        value_fn=lambda d, c: (
            None if (p := d.cheap_probability(float(c.controls["price_threshold"]))) is None else round(p * 100, 1)
        ),
        attrs_fn=lambda d, c: {"threshold": c.controls["price_threshold"], "horizon_hours": 24},
    ),
    PstrykSensorDescription(
        key="forecast_accuracy",
        translation_key="forecast_accuracy",
        native_unit_of_measurement="PLN/MWh",
        suggested_display_precision=1,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_accuracy,
        attrs_fn=lambda d, c: {
            "metric": "MAE dzień 1 (rynek, PLN/MWh)",
            "live_mae": c.history.live_mae(),
            "backtest_mae": d.model_info.get("backtest_mae"),
            "weights": d.model_info.get("weights"),
            "market_reference": d.model_info.get("market_reference"),
            "trained_at": d.model_info.get("trained_at"),
        },
    ),
    PstrykSensorDescription(
        key="forecast_confidence",
        translation_key="forecast_confidence",
        native_unit_of_measurement=PERCENTAGE,
        suggested_display_precision=0,
        value_fn=lambda d, c: None if (x := d.forecast_confidence()) is None else round(x * 100, 1),
    ),
    PstrykSensorDescription(
        key="pstryk_api_status",
        translation_key="pstryk_api_status",
        device_class=SensorDeviceClass.ENUM,
        options=STATUS_OPTIONS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_status("pstryk"),
        attrs_fn=lambda d, c: (
            c.status["pstryk"].as_dict()
            | {"budget_remaining": c.pstryk.budget.remaining(), "requests": c.pstryk.request_count}
        ),
    ),
    PstrykSensorDescription(
        key="market_data_status",
        translation_key="market_data_status",
        device_class=SensorDeviceClass.ENUM,
        options=STATUS_OPTIONS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=_market_status,
        attrs_fn=lambda d, c: (
            {n: c.status[n].as_dict() for n in ("tge", "entsoe", "pse", "weather")}
            | {"market_reference": d.flags.get("market_reference")}
        ),
    ),
    PstrykSensorDescription(
        key="mqtt_status",
        translation_key="mqtt_status",
        device_class=SensorDeviceClass.ENUM,
        options=STATUS_OPTIONS,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d, c: c.publisher.status if c.controls["mqtt_enabled"] else "disabled",
        attrs_fn=lambda d, c: {
            "prefix": c.publisher.prefix,
            "published": c.publisher.published,
            "last_publish": iso(c.publisher.last_publish),
        },
    ),
    PstrykSensorDescription(
        key="last_update",
        translation_key="last_update",
        device_class=SensorDeviceClass.TIMESTAMP,
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda d, c: d.now,
        attrs_fn=lambda d, c: {"reason": d.flags.get("reason"), "last_main_calculation": iso(c.last_main_calc)},
    ),
    PstrykSensorDescription(
        key="buffer_target_temperature",
        translation_key="buffer_target_temperature",
        native_unit_of_measurement=UnitOfTemperature.CELSIUS,
        device_class=SensorDeviceClass.TEMPERATURE,
        value_fn=_buffer("target_temperature"),
        attrs_fn=lambda d, c: d.buffer.to_dict(include_steps=False) if d.buffer else {},
    ),
    PstrykSensorDescription(
        key="buffer_next_window",
        translation_key="buffer_next_window",
        device_class=SensorDeviceClass.TIMESTAMP,
        value_fn=_buffer("recommended_start"),
        attrs_fn=lambda d, c: (
            {"stop": iso(d.buffer.recommended_stop), "duration_h": d.buffer.recommended_duration_h} if d.buffer else {}
        ),
    ),
    PstrykSensorDescription(
        key="buffer_expected_cost",
        translation_key="buffer_expected_cost",
        native_unit_of_measurement=CURRENCY,
        device_class=SensorDeviceClass.MONETARY,
        suggested_display_precision=2,
        value_fn=_buffer("expected_cost_pln"),
        attrs_fn=lambda d, c: {"horizon_hours": 24, "energy_kwh": _buffer("expected_energy_kwh")(d, c)},
    ),
    PstrykSensorDescription(
        key="buffer_savings",
        translation_key="buffer_savings",
        native_unit_of_measurement=CURRENCY,
        device_class=SensorDeviceClass.MONETARY,
        suggested_display_precision=2,
        value_fn=_buffer("expected_savings_pln"),
        attrs_fn=lambda d, c: {"reference": "termostat z histerezą wokół temperatury docelowej"},
    ),
    PstrykSensorDescription(
        key="buffer_plan_reason",
        translation_key="buffer_plan_reason",
        value_fn=lambda d, c: d.buffer.optimization_reason[:250] if d.buffer else None,
        attrs_fn=lambda d, c: (
            {
                "mode": d.buffer.mode,
                "confidence": round(d.buffer.optimization_confidence, 3),
                "schedule": [s.to_dict() for s in d.buffer.steps[:48]],
            }
            if d.buffer
            else {}
        ),
    ),
    # --- Pstryk meter / financial data
    PstrykSensorDescription(
        key="energy_import_today",
        translation_key="energy_import_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda d, c: _sum(_today_frames(d), "import_kwh"),
    ),
    PstrykSensorDescription(
        key="energy_export_today",
        translation_key="energy_export_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda d, c: _sum(_today_frames(d), "export_kwh"),
    ),
    PstrykSensorDescription(
        key="energy_balance_today",
        translation_key="energy_balance_today",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn=lambda d, c: _sum(_today_frames(d), "balance_kwh"),
    ),
    PstrykSensorDescription(
        key="cost_today",
        translation_key="cost_today",
        native_unit_of_measurement=CURRENCY,
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=lambda d, c: _sum(_today_frames(d), "import_cost"),
    ),
    PstrykSensorDescription(
        key="sold_value_today",
        translation_key="sold_value_today",
        native_unit_of_measurement=CURRENCY,
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=lambda d, c: _sum(_today_frames(d), "sold_value"),
    ),
    PstrykSensorDescription(
        key="balance_today",
        translation_key="balance_today",
        native_unit_of_measurement=CURRENCY,
        device_class=SensorDeviceClass.MONETARY,
        suggested_display_precision=2,
        value_fn=lambda d, c: _sum(_today_frames(d), "balance_value"),
    ),
    PstrykSensorDescription(
        key="energy_import_month",
        translation_key="energy_import_month",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda d, c: _month(d, "import_kwh"),
    ),
    PstrykSensorDescription(
        key="energy_export_month",
        translation_key="energy_export_month",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        device_class=SensorDeviceClass.ENERGY,
        state_class=SensorStateClass.TOTAL,
        value_fn=lambda d, c: _month(d, "export_kwh"),
    ),
    PstrykSensorDescription(
        key="energy_balance_month",
        translation_key="energy_balance_month",
        native_unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
        value_fn=lambda d, c: _month(d, "balance_kwh"),
    ),
    PstrykSensorDescription(
        key="cost_month",
        translation_key="cost_month",
        native_unit_of_measurement=CURRENCY,
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        suggested_display_precision=2,
        value_fn=lambda d, c: _month(d, "import_cost"),
    ),
    PstrykSensorDescription(
        key="balance_month",
        translation_key="balance_month",
        native_unit_of_measurement=CURRENCY,
        device_class=SensorDeviceClass.MONETARY,
        suggested_display_precision=2,
        value_fn=lambda d, c: _month(d, "balance_value"),
        attrs_fn=lambda d, c: {"summary": c.monthly_summary},
    ),
)


def _r(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


async def async_setup_entry(
    hass: HomeAssistant, entry: PstrykAIConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [PstrykSensor(coordinator, d) for d in SENSORS]
    entities += [DeviceScheduleSensor(coordinator, p.name, p.slug) for p in coordinator.settings.profiles]
    async_add_entities(entities)


class PstrykSensor(PstrykAIEntity, SensorEntity):
    _platform = "sensor"
    entity_description: PstrykSensorDescription
    # Large time series must not bloat the recorder database.
    _unrecorded_attributes = frozenset({"prices", "series", "schedule", "summary", "hours"})

    def __init__(self, coordinator: PstrykAICoordinator, description: PstrykSensorDescription) -> None:
        super().__init__(coordinator, description.key)
        self.entity_description = description

    @property
    def native_value(self) -> Any:
        if self.coordinator.data is None:
            return None
        return self.entity_description.value_fn(self.coordinator.data, self.coordinator)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self.coordinator.data is None or self.entity_description.attrs_fn is None:
            return None
        return self.entity_description.attrs_fn(self.coordinator.data, self.coordinator)


class DeviceScheduleSensor(PstrykAIEntity, SensorEntity):
    _platform = "sensor"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "device_schedule"
    _unrecorded_attributes = frozenset({"hours"})

    def __init__(self, coordinator: PstrykAICoordinator, name: str, slug: str) -> None:
        super().__init__(coordinator, f"schedule_{slug}")
        self._profile = name
        self._attr_translation_placeholders = {"name": name}

    def _schedule(self):
        if self.coordinator.data is None:
            return None
        return next((s for s in self.coordinator.data.schedules if s.profile == self._profile), None)

    @property
    def native_value(self) -> datetime | None:
        s = self._schedule()
        return s.next_start if s else None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        s = self._schedule()
        return s.to_dict() if s else None
