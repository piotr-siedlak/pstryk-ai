"""Config flow (multi-step wizard) and options flow."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, timedelta
import json
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util
import voluptuous as vol

from .api.base import ProviderAuthError, ProviderError, ProviderNotFound, ProviderRateLimited
from .api.entsoe import EntsoeClient
from .api.pse import PseClient
from .api.pstryk import PstrykClient, key_fingerprint
from .api.weather import WeatherClient
from .const import (
    BUFFER_STRATEGIES,
    BUFFER_STRATEGY_COST,
    COMMAND_BINARY,
    COMMAND_FORMATS,
    CONF_API_KEY,
    CONF_AUTO_CALIBRATE_TARIFF,
    CONF_AUTO_RETRAIN,
    CONF_BASE_LOAD_KW,
    CONF_BUFFER_BOTTOM_ENTITY,
    CONF_BUFFER_BOTTOM_KEY,
    CONF_BUFFER_BOTTOM_TOPIC,
    CONF_BUFFER_ENABLED,
    CONF_BUFFER_MAX_T,
    CONF_BUFFER_MIN_T,
    CONF_BUFFER_STRATEGY,
    CONF_BUFFER_TARGET_T,
    CONF_BUFFER_TOP_ENTITY,
    CONF_BUFFER_TOP_KEY,
    CONF_BUFFER_TOP_TOPIC,
    CONF_BUFFER_VOLUME_L,
    CONF_CHEAP_HOURS,
    CONF_DEVICE_PROFILES,
    CONF_DHW_BOTTOM_ENTITY,
    CONF_DHW_BOTTOM_KEY,
    CONF_DHW_BOTTOM_TOPIC,
    CONF_DHW_ENABLED,
    CONF_DHW_HP_MODE,
    CONF_DHW_LITERS_DAY,
    CONF_DHW_LOSS_KW_K,
    CONF_DHW_MAX_T,
    CONF_DHW_MIN_T,
    CONF_DHW_PRIORITY,
    CONF_DHW_READY_T,
    CONF_DHW_READY_TIMES,
    CONF_DHW_TARGET_T,
    CONF_DHW_TOP_ENTITY,
    CONF_DHW_TOP_KEY,
    CONF_DHW_TOP_TOPIC,
    CONF_DHW_VALVE_TOPIC,
    CONF_DHW_VOLUME_L,
    CONF_DIST_OFFPEAK_HOURS,
    CONF_DIST_PEAK2_HOURS,
    CONF_DIST_RATE_OFFPEAK,
    CONF_DIST_RATE_PEAK,
    CONF_DIST_RATE_PEAK2,
    CONF_DIST_TARIFF,
    CONF_DIST_WEEKEND_OFFPEAK,
    CONF_ENERGY_MARGIN,
    CONF_ENTSOE_TOKEN,
    CONF_EUR_PLN,
    CONF_EXCISE,
    CONF_FORECAST_HORIZON_H,
    CONF_FORECAST_MODEL,
    CONF_HEARTBEAT,
    CONF_HEAT_LOSS_COEFF,
    CONF_HISTORY_DAYS,
    CONF_HP_COP,
    CONF_HP_COP_CURVE,
    CONF_HP_ELECTRIC_KW,
    CONF_HP_MAX_T,
    CONF_HP_MIN_MODULATION,
    CONF_HP_POWER_ENTITY,
    CONF_HP_POWER_KEY,
    CONF_HP_POWER_TOPIC,
    CONF_HP_THERMAL_KW,
    CONF_INDOOR_BASE_T,
    CONF_INPUT_MAX_AGE_MIN,
    CONF_LATITUDE,
    CONF_LEARN_APPLY,
    CONF_LEARN_COP,
    CONF_LEARN_DHW_PROFILE,
    CONF_LEARN_LOSSES,
    CONF_LEGIONELLA_DAYS,
    CONF_LEGIONELLA_ENABLED,
    CONF_LEGIONELLA_T,
    CONF_LONGITUDE,
    CONF_MARKET_PROVIDER,
    CONF_MAX_SPECULATIVE_H,
    CONF_MAX_STARTS,
    CONF_MIN_OFFTIME_H,
    CONF_MIN_RUNTIME_H,
    CONF_MQTT_DISCOVERY,
    CONF_MQTT_ENABLED,
    CONF_MQTT_EVCC,
    CONF_MQTT_PREFIX,
    CONF_MQTT_QOS,
    CONF_MQTT_RETAIN,
    CONF_MQTT_TOPICS,
    CONF_NOTIFY_FALLBACK,
    CONF_NOTIFY_NEGATIVE,
    CONF_NOTIFY_SERVICE,
    CONF_NOTIFY_STALE,
    CONF_NOTIFY_TOMORROW,
    CONF_OPTIMIZE_ALL_IN,
    CONF_OUTDOOR_TEMP_ENTITY,
    CONF_OUTDOOR_TEMP_KEY,
    CONF_OUTDOOR_TEMP_TOPIC,
    CONF_POWER_LIMIT_ENABLED,
    CONF_POWER_LIMIT_KW,
    CONF_POWER_UNIT,
    CONF_PRICE_INCLUDES_DISTRIBUTION,
    CONF_PRICE_THRESHOLD,
    CONF_PROSUMER,
    CONF_PSE_ENABLED,
    CONF_PV_ENABLED,
    CONF_PV_KWP,
    CONF_PV_PR,
    CONF_RISK_AVERSION,
    CONF_SHOW_PANEL,
    CONF_SPENDS_ENABLED,
    CONF_SPENDS_HISTORY,
    CONF_STATISTICS_IMPORT,
    CONF_TGE_ENABLED,
    CONF_THERMAL_LOSS_KW_K,
    CONF_USE_HA_LOCATION,
    CONF_VAR_DISTRIBUTION,
    CONF_VAT_RATE,
    CONF_WEATHER_MODEL,
    CONF_WEATHER_REFRESH_H,
    DEFAULT_BUFFER_MAX_T,
    DEFAULT_BUFFER_MIN_T,
    DEFAULT_BUFFER_TARGET_T,
    DEFAULT_BUFFER_VOLUME_L,
    DEFAULT_CHEAP_HOURS,
    DEFAULT_ENERGY_MARGIN,
    DEFAULT_EUR_PLN,
    DEFAULT_EXCISE,
    DEFAULT_HEAT_LOSS_COEFF,
    DEFAULT_HISTORY_DAYS,
    DEFAULT_HORIZON_H,
    DEFAULT_HP_COP,
    DEFAULT_HP_ELECTRIC_KW,
    DEFAULT_HP_MIN_MODULATION,
    DEFAULT_HP_THERMAL_KW,
    DEFAULT_INDOOR_BASE_T,
    DEFAULT_INPUT_MAX_AGE_MIN,
    DEFAULT_MAX_SPECULATIVE_H,
    DEFAULT_MAX_STARTS,
    DEFAULT_MIN_OFFTIME_H,
    DEFAULT_MIN_RUNTIME_H,
    DEFAULT_MQTT_PREFIX,
    DEFAULT_MQTT_QOS,
    DEFAULT_PRICE_THRESHOLD,
    DEFAULT_RISK_AVERSION,
    DEFAULT_THERMAL_LOSS_KW_K,
    DEFAULT_VAR_DISTRIBUTION,
    DEFAULT_VAT_RATE,
    DEFAULT_WEATHER_MODEL,
    DEFAULT_WEATHER_REFRESH_H,
    DHW_HP_MODES,
    DHW_HP_VALVE,
    DOMAIN,
    FORECAST_MODEL_AUTO,
    FORECAST_MODELS,
    HEATER_KIND_ELECTRIC,
    HEATER_KINDS,
    MARKET_PROVIDER_ENTSOE,
    MARKET_PROVIDERS,
    NAME,
    POWER_UNITS,
    WEATHER_MODELS,
)
from .mqtt.schemas import TOPICS, resolve_topic, topic_field, validate_topic
from .optimization.dhw import parse_times
from .settings import parse_profiles
from .settings_ext import parse_steps
from .tariff import DIST_NONE, DIST_TARIFFS, parse_hour_ranges

_LOGGER = logging.getLogger(__name__)


def _num(min_v: float, max_v: float, step: float | str, unit: str | None = None) -> selector.NumberSelector:
    config = selector.NumberSelectorConfig(min=min_v, max=max_v, step=step, mode=selector.NumberSelectorMode.BOX)
    if unit:
        config["unit_of_measurement"] = unit
    return selector.NumberSelector(config)


def _sel(options: list[str], key: str) -> selector.SelectSelector:
    return selector.SelectSelector(
        selector.SelectSelectorConfig(options=options, translation_key=key, mode=selector.SelectSelectorMode.DROPDOWN)
    )


def _d(values: Mapping[str, Any], key: str, default: Any) -> Any:
    v = values.get(key)
    return default if v is None else v


def schema_pstryk(v: Mapping[str, Any], include_key: bool) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if include_key:
        fields[vol.Required(CONF_API_KEY, default=v.get(CONF_API_KEY, ""))] = selector.TextSelector(
            selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
        )
    fields.update(
        {
            vol.Required(CONF_PROSUMER, default=_d(v, CONF_PROSUMER, False)): bool,
            vol.Required(CONF_VAT_RATE, default=_d(v, CONF_VAT_RATE, DEFAULT_VAT_RATE)): _num(0, 0.5, 0.01),
            vol.Required(CONF_ENERGY_MARGIN, default=_d(v, CONF_ENERGY_MARGIN, DEFAULT_ENERGY_MARGIN)): _num(
                -1, 2, "any", "PLN/kWh"
            ),
            vol.Required(CONF_EXCISE, default=_d(v, CONF_EXCISE, DEFAULT_EXCISE)): _num(0, 0.1, "any", "PLN/kWh"),
            vol.Required(CONF_VAR_DISTRIBUTION, default=_d(v, CONF_VAR_DISTRIBUTION, DEFAULT_VAR_DISTRIBUTION)): _num(
                0, 2, "any", "PLN/kWh"
            ),
            vol.Required(
                CONF_PRICE_INCLUDES_DISTRIBUTION, default=_d(v, CONF_PRICE_INCLUDES_DISTRIBUTION, False)
            ): bool,
            vol.Required(CONF_AUTO_CALIBRATE_TARIFF, default=_d(v, CONF_AUTO_CALIBRATE_TARIFF, False)): bool,
            vol.Required(CONF_SPENDS_ENABLED, default=_d(v, CONF_SPENDS_ENABLED, True)): bool,
            vol.Required(CONF_SPENDS_HISTORY, default=_d(v, CONF_SPENDS_HISTORY, True)): bool,
            vol.Required(CONF_STATISTICS_IMPORT, default=_d(v, CONF_STATISTICS_IMPORT, False)): bool,
        }
    )
    return vol.Schema(fields)


def schema_location(v: Mapping[str, Any], lat: float, lon: float) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_USE_HA_LOCATION, default=_d(v, CONF_USE_HA_LOCATION, True)): bool,
            vol.Optional(CONF_LATITUDE, default=_d(v, CONF_LATITUDE, lat)): _num(-90, 90, "any"),
            vol.Optional(CONF_LONGITUDE, default=_d(v, CONF_LONGITUDE, lon)): _num(-180, 180, "any"),
        }
    )


def schema_market(v: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_MARKET_PROVIDER, default=_d(v, CONF_MARKET_PROVIDER, MARKET_PROVIDER_ENTSOE)): _sel(
                MARKET_PROVIDERS, "market_provider"
            ),
            vol.Optional(CONF_ENTSOE_TOKEN, default=v.get(CONF_ENTSOE_TOKEN, "")): selector.TextSelector(
                selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
            ),
            vol.Required(CONF_PSE_ENABLED, default=_d(v, CONF_PSE_ENABLED, True)): bool,
            vol.Required(CONF_TGE_ENABLED, default=_d(v, CONF_TGE_ENABLED, False)): bool,
            vol.Required(CONF_EUR_PLN, default=_d(v, CONF_EUR_PLN, DEFAULT_EUR_PLN)): _num(1, 10, "any"),
        }
    )


def schema_weather(v: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_WEATHER_MODEL, default=_d(v, CONF_WEATHER_MODEL, DEFAULT_WEATHER_MODEL)): _sel(
                WEATHER_MODELS, "weather_model"
            ),
            vol.Required(
                CONF_WEATHER_REFRESH_H, default=_d(v, CONF_WEATHER_REFRESH_H, DEFAULT_WEATHER_REFRESH_H)
            ): _num(1, 12, 1, "h"),
            vol.Required(CONF_HISTORY_DAYS, default=_d(v, CONF_HISTORY_DAYS, DEFAULT_HISTORY_DAYS)): _num(
                60, 1100, 1, "d"
            ),
        }
    )


def schema_forecast(v: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_FORECAST_HORIZON_H, default=_d(v, CONF_FORECAST_HORIZON_H, DEFAULT_HORIZON_H)): _num(
                24, 168, 1, "h"
            ),
            vol.Required(CONF_FORECAST_MODEL, default=_d(v, CONF_FORECAST_MODEL, FORECAST_MODEL_AUTO)): _sel(
                FORECAST_MODELS, "forecast_model"
            ),
            vol.Required(CONF_AUTO_RETRAIN, default=_d(v, CONF_AUTO_RETRAIN, True)): bool,
            vol.Required(CONF_RISK_AVERSION, default=_d(v, CONF_RISK_AVERSION, DEFAULT_RISK_AVERSION)): _num(
                0, 1, 0.05
            ),
            vol.Required(
                CONF_MAX_SPECULATIVE_H, default=_d(v, CONF_MAX_SPECULATIVE_H, DEFAULT_MAX_SPECULATIVE_H)
            ): _num(12, 168, 1, "h"),
        }
    )


def schema_optimization(v: Mapping[str, Any]) -> vol.Schema:
    profiles = v.get(CONF_DEVICE_PROFILES)
    if isinstance(profiles, list):
        profiles = json.dumps(profiles, ensure_ascii=False)
    return vol.Schema(
        {
            vol.Required(CONF_CHEAP_HOURS, default=_d(v, CONF_CHEAP_HOURS, DEFAULT_CHEAP_HOURS)): _num(1, 24, 1, "h"),
            vol.Required(CONF_PRICE_THRESHOLD, default=_d(v, CONF_PRICE_THRESHOLD, DEFAULT_PRICE_THRESHOLD)): _num(
                -2, 5, 0.01, "PLN/kWh"
            ),
            vol.Optional(CONF_DEVICE_PROFILES, default=profiles or "[]"): selector.TextSelector(
                selector.TextSelectorConfig(multiline=True)
            ),
        }
    )


def schema_buffer(v: Mapping[str, Any]) -> vol.Schema:
    temp_sel = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor", device_class="temperature"))
    fields: dict[Any, Any] = {
        vol.Required(CONF_BUFFER_ENABLED, default=_d(v, CONF_BUFFER_ENABLED, False)): bool,
    }
    for key in (CONF_BUFFER_TOP_ENTITY, CONF_BUFFER_BOTTOM_ENTITY, CONF_OUTDOOR_TEMP_ENTITY):
        fields[vol.Optional(key, description={"suggested_value": v.get(key) or None})] = temp_sel
    for key in BUFFER_TEXT_KEYS:
        fields[vol.Optional(key, description={"suggested_value": v.get(key) or ""})] = selector.TextSelector()
    fields[vol.Required(CONF_HP_MAX_T, default=_d(v, CONF_HP_MAX_T, 55.0))] = _num(30, 80, 0.5, "°C")
    fields[vol.Required(CONF_HP_MIN_MODULATION, default=_d(v, CONF_HP_MIN_MODULATION, DEFAULT_HP_MIN_MODULATION))] = (
        _num(10, 100, 5, "%")
    )
    fields[vol.Required(CONF_INPUT_MAX_AGE_MIN, default=_d(v, CONF_INPUT_MAX_AGE_MIN, DEFAULT_INPUT_MAX_AGE_MIN))] = (
        _num(2, 720, 1, "min")
    )
    fields.update(
        {
            vol.Required(CONF_BUFFER_VOLUME_L, default=_d(v, CONF_BUFFER_VOLUME_L, DEFAULT_BUFFER_VOLUME_L)): _num(
                20, 10000, 10, "L"
            ),
            vol.Required(CONF_BUFFER_MIN_T, default=_d(v, CONF_BUFFER_MIN_T, DEFAULT_BUFFER_MIN_T)): _num(
                10, 70, 0.5, "°C"
            ),
            vol.Required(CONF_BUFFER_MAX_T, default=_d(v, CONF_BUFFER_MAX_T, DEFAULT_BUFFER_MAX_T)): _num(
                20, 80, 0.5, "°C"
            ),
            vol.Required(CONF_BUFFER_TARGET_T, default=_d(v, CONF_BUFFER_TARGET_T, DEFAULT_BUFFER_TARGET_T)): _num(
                15, 75, 0.5, "°C"
            ),
            vol.Required(CONF_HP_ELECTRIC_KW, default=_d(v, CONF_HP_ELECTRIC_KW, DEFAULT_HP_ELECTRIC_KW)): _num(
                0.3, 50, 0.1, "kW"
            ),
            vol.Required(CONF_HP_THERMAL_KW, default=_d(v, CONF_HP_THERMAL_KW, DEFAULT_HP_THERMAL_KW)): _num(
                0.5, 100, 0.1, "kW"
            ),
            vol.Required(CONF_HP_COP, default=_d(v, CONF_HP_COP, DEFAULT_HP_COP)): _num(1, 7, 0.1),
            vol.Optional(CONF_HP_COP_CURVE, default=v.get(CONF_HP_COP_CURVE, "")): str,
            vol.Required(
                CONF_THERMAL_LOSS_KW_K, default=_d(v, CONF_THERMAL_LOSS_KW_K, DEFAULT_THERMAL_LOSS_KW_K)
            ): _num(0, 0.1, "any", "kW/K"),
            vol.Required(CONF_HEAT_LOSS_COEFF, default=_d(v, CONF_HEAT_LOSS_COEFF, DEFAULT_HEAT_LOSS_COEFF)): _num(
                0, 5, 0.01, "kW/K"
            ),
            vol.Required(CONF_INDOOR_BASE_T, default=_d(v, CONF_INDOOR_BASE_T, DEFAULT_INDOOR_BASE_T)): _num(
                10, 25, 0.5, "°C"
            ),
            vol.Required(CONF_MIN_RUNTIME_H, default=_d(v, CONF_MIN_RUNTIME_H, DEFAULT_MIN_RUNTIME_H)): _num(
                1, 6, 1, "h"
            ),
            vol.Required(CONF_MIN_OFFTIME_H, default=_d(v, CONF_MIN_OFFTIME_H, DEFAULT_MIN_OFFTIME_H)): _num(
                0, 6, 1, "h"
            ),
            vol.Required(CONF_MAX_STARTS, default=_d(v, CONF_MAX_STARTS, DEFAULT_MAX_STARTS)): _num(1, 24, 1),
            vol.Required(CONF_BUFFER_STRATEGY, default=_d(v, CONF_BUFFER_STRATEGY, BUFFER_STRATEGY_COST)): _sel(
                BUFFER_STRATEGIES, "buffer_strategy"
            ),
        }
    )
    return vol.Schema(fields)


BUFFER_TEXT_KEYS = (
    CONF_BUFFER_TOP_TOPIC,
    CONF_BUFFER_TOP_KEY,
    CONF_BUFFER_BOTTOM_TOPIC,
    CONF_BUFFER_BOTTOM_KEY,
    CONF_OUTDOOR_TEMP_TOPIC,
    CONF_OUTDOOR_TEMP_KEY,
)
BUFFER_ENTITY_KEYS = (CONF_BUFFER_TOP_ENTITY, CONF_BUFFER_BOTTOM_ENTITY, CONF_OUTDOOR_TEMP_ENTITY)


def _text(v: Mapping[str, Any], key: str) -> vol.Optional:
    return vol.Optional(key, description={"suggested_value": v.get(key) or ""})


def _temp_entity(v: Mapping[str, Any], key: str) -> vol.Optional:
    return vol.Optional(key, description={"suggested_value": v.get(key) or None})


TEMP_SEL = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor", device_class="temperature"))


def schema_heater(v: Mapping[str, Any], prefix: str) -> vol.Schema:
    p = f"{prefix}_heater_"
    return vol.Schema(
        {
            vol.Required(p + "enabled", default=_d(v, p + "enabled", False)): bool,
            vol.Required(p + "kind", default=_d(v, p + "kind", HEATER_KIND_ELECTRIC)): _sel(
                HEATER_KINDS, "heater_kind"
            ),
            vol.Required(p + "steps_kw", default=str(_d(v, p + "steps_kw", "3"))): str,
            vol.Required(p + "efficiency", default=_d(v, p + "efficiency", 1.0)): _num(0.3, 1.2, "any"),
            vol.Required(p + "fuel_price", default=_d(v, p + "fuel_price", 0.35)): _num(0, 5, "any", "PLN/kWh"),
            _text(v, p + "max_temperature"): selector.TextSelector(),
            _text(v, p + "command_topic"): selector.TextSelector(),
            vol.Required(p + "command_format", default=_d(v, p + "command_format", COMMAND_BINARY)): _sel(
                COMMAND_FORMATS, "command_format"
            ),
            _text(v, p + "state_topic"): selector.TextSelector(),
            _text(v, p + "state_json_key"): selector.TextSelector(),
        }
    )


DHW_TEXT_KEYS = (
    CONF_DHW_TOP_TOPIC,
    CONF_DHW_TOP_KEY,
    CONF_DHW_BOTTOM_TOPIC,
    CONF_DHW_BOTTOM_KEY,
    CONF_DHW_VALVE_TOPIC,
)


def schema_dhw(v: Mapping[str, Any]) -> vol.Schema:
    fields: dict[Any, Any] = {vol.Required(CONF_DHW_ENABLED, default=_d(v, CONF_DHW_ENABLED, False)): bool}
    for key in (CONF_DHW_TOP_ENTITY, CONF_DHW_BOTTOM_ENTITY):
        fields[_temp_entity(v, key)] = TEMP_SEL
    for key in (CONF_DHW_TOP_TOPIC, CONF_DHW_TOP_KEY, CONF_DHW_BOTTOM_TOPIC, CONF_DHW_BOTTOM_KEY):
        fields[_text(v, key)] = selector.TextSelector()
    fields.update(
        {
            vol.Required(CONF_DHW_VOLUME_L, default=_d(v, CONF_DHW_VOLUME_L, 200)): _num(30, 2000, 10, "L"),
            vol.Required(CONF_DHW_MIN_T, default=_d(v, CONF_DHW_MIN_T, 40.0)): _num(20, 70, 0.5, "°C"),
            vol.Required(CONF_DHW_MAX_T, default=_d(v, CONF_DHW_MAX_T, 60.0)): _num(30, 85, 0.5, "°C"),
            vol.Required(CONF_DHW_TARGET_T, default=_d(v, CONF_DHW_TARGET_T, 50.0)): _num(30, 80, 0.5, "°C"),
            vol.Required(CONF_DHW_READY_TIMES, default=str(_d(v, CONF_DHW_READY_TIMES, "06:00,19:00"))): str,
            vol.Required(CONF_DHW_READY_T, default=_d(v, CONF_DHW_READY_T, 45.0)): _num(30, 70, 0.5, "°C"),
            vol.Required(CONF_DHW_LITERS_DAY, default=_d(v, CONF_DHW_LITERS_DAY, 150)): _num(0, 2000, 5, "L"),
            vol.Required(CONF_DHW_LOSS_KW_K, default=_d(v, CONF_DHW_LOSS_KW_K, 0.002)): _num(0, 0.05, "any", "kW/K"),
            vol.Required(CONF_DHW_HP_MODE, default=_d(v, CONF_DHW_HP_MODE, DHW_HP_VALVE)): _sel(
                DHW_HP_MODES, "dhw_heat_pump_mode"
            ),
            vol.Required(CONF_DHW_PRIORITY, default=_d(v, CONF_DHW_PRIORITY, True)): bool,
            _text(v, CONF_DHW_VALVE_TOPIC): selector.TextSelector(),
            vol.Required(CONF_LEGIONELLA_ENABLED, default=_d(v, CONF_LEGIONELLA_ENABLED, False)): bool,
            vol.Required(CONF_LEGIONELLA_T, default=_d(v, CONF_LEGIONELLA_T, 60.0)): _num(55, 80, 0.5, "°C"),
            vol.Required(CONF_LEGIONELLA_DAYS, default=_d(v, CONF_LEGIONELLA_DAYS, 7)): _num(1, 30, 1, "d"),
        }
    )
    return vol.Schema(fields)


POWER_TEXT_KEYS = (CONF_HP_POWER_TOPIC, CONF_HP_POWER_KEY)


def schema_power(v: Mapping[str, Any]) -> vol.Schema:
    power_sel = selector.EntitySelector(selector.EntitySelectorConfig(domain="sensor", device_class="power"))
    return vol.Schema(
        {
            vol.Required(CONF_POWER_LIMIT_ENABLED, default=_d(v, CONF_POWER_LIMIT_ENABLED, False)): bool,
            vol.Required(CONF_POWER_LIMIT_KW, default=_d(v, CONF_POWER_LIMIT_KW, 11.0)): _num(1, 100, 0.5, "kW"),
            vol.Required(CONF_BASE_LOAD_KW, default=_d(v, CONF_BASE_LOAD_KW, 0.4)): _num(0, 20, 0.1, "kW"),
            _temp_entity(v, CONF_HP_POWER_ENTITY): power_sel,
            _text(v, CONF_HP_POWER_TOPIC): selector.TextSelector(),
            _text(v, CONF_HP_POWER_KEY): selector.TextSelector(),
            vol.Required(CONF_POWER_UNIT, default=str(_d(v, CONF_POWER_UNIT, "kw")).lower()): _sel(
                [u.lower() for u in POWER_UNITS], "power_unit"
            ),
        }
    )


def schema_tariff(v: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_DIST_TARIFF, default=str(_d(v, CONF_DIST_TARIFF, DIST_NONE)).lower()): _sel(
                [t.lower() for t in DIST_TARIFFS], "distribution_tariff"
            ),
            vol.Required(CONF_DIST_RATE_PEAK, default=_d(v, CONF_DIST_RATE_PEAK, 0.0)): _num(0, 3, "any", "PLN/kWh"),
            vol.Required(CONF_DIST_RATE_OFFPEAK, default=_d(v, CONF_DIST_RATE_OFFPEAK, 0.0)): _num(
                0, 3, "any", "PLN/kWh"
            ),
            vol.Required(CONF_DIST_RATE_PEAK2, default=_d(v, CONF_DIST_RATE_PEAK2, 0.0)): _num(0, 3, "any", "PLN/kWh"),
            _text(v, CONF_DIST_OFFPEAK_HOURS): selector.TextSelector(),
            _text(v, CONF_DIST_PEAK2_HOURS): selector.TextSelector(),
            vol.Required(CONF_DIST_WEEKEND_OFFPEAK, default=_d(v, CONF_DIST_WEEKEND_OFFPEAK, False)): bool,
            vol.Required(CONF_OPTIMIZE_ALL_IN, default=_d(v, CONF_OPTIMIZE_ALL_IN, False)): bool,
        }
    )


def schema_pv(v: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_PV_ENABLED, default=_d(v, CONF_PV_ENABLED, False)): bool,
            vol.Required(CONF_PV_KWP, default=_d(v, CONF_PV_KWP, 5.0)): _num(0.1, 100, 0.1, "kWp"),
            vol.Required(CONF_PV_PR, default=_d(v, CONF_PV_PR, 0.8)): _num(0.3, 1.0, 0.01),
            vol.Required(CONF_BASE_LOAD_KW, default=_d(v, CONF_BASE_LOAD_KW, 0.4)): _num(0, 20, 0.1, "kW"),
        }
    )


def schema_learning(v: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(k, default=_d(v, k, False)): bool
            for k in (CONF_LEARN_LOSSES, CONF_LEARN_DHW_PROFILE, CONF_LEARN_COP, CONF_LEARN_APPLY)
        }
    )


def schema_notifications(v: Mapping[str, Any]) -> vol.Schema:
    fields: dict[Any, Any] = {
        vol.Required(k, default=_d(v, k, False)): bool
        for k in (CONF_NOTIFY_TOMORROW, CONF_NOTIFY_NEGATIVE, CONF_NOTIFY_FALLBACK, CONF_NOTIFY_STALE, CONF_HEARTBEAT)
    }
    fields[_text(v, CONF_NOTIFY_SERVICE)] = selector.TextSelector()
    return vol.Schema(fields)


def schema_mqtt(v: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_MQTT_ENABLED, default=_d(v, CONF_MQTT_ENABLED, True)): bool,
            vol.Required(CONF_MQTT_PREFIX, default=_d(v, CONF_MQTT_PREFIX, DEFAULT_MQTT_PREFIX)): str,
            vol.Required(CONF_MQTT_DISCOVERY, default=_d(v, CONF_MQTT_DISCOVERY, False)): bool,
            vol.Required(CONF_MQTT_QOS, default=str(_d(v, CONF_MQTT_QOS, DEFAULT_MQTT_QOS))): _sel(
                ["0", "1", "2"], "mqtt_qos"
            ),
            vol.Required(CONF_MQTT_RETAIN, default=_d(v, CONF_MQTT_RETAIN, True)): bool,
            vol.Required(CONF_MQTT_EVCC, default=_d(v, CONF_MQTT_EVCC, False)): bool,
        }
    )


def _valid_input_topic(value: Any) -> bool:
    """Exact topic to subscribe to: empty, or no wildcards / empty levels."""
    text = str(value or "").strip()
    if not text:
        return True
    return "#" not in text and "+" not in text and all(text.strip("/").split("/")) and len(text) <= 250


def validate_section(step: str, data: dict[str, Any]) -> dict[str, str]:
    errors: dict[str, str] = {}
    if step == "optimization":
        raw = data.get(CONF_DEVICE_PROFILES) or "[]"
        try:
            parsed = json.loads(raw)
            if not isinstance(parsed, list):
                raise ValueError
            profiles = parse_profiles(parsed)
            if len(profiles) != len(parsed):
                raise ValueError
        except ValueError:
            errors[CONF_DEVICE_PROFILES] = "invalid_profiles"
        else:
            if not all(_valid_input_topic(p.temperature_topic) for p in profiles):
                errors[CONF_DEVICE_PROFILES] = "invalid_input_topic"
    if step == "buffer" and float(data.get(CONF_BUFFER_MIN_T, 0)) >= float(data.get(CONF_BUFFER_MAX_T, 100)):
        errors[CONF_BUFFER_MAX_T] = "invalid_temperature_range"
    topic_keys = {
        "buffer": (CONF_BUFFER_TOP_TOPIC, CONF_BUFFER_BOTTOM_TOPIC, CONF_OUTDOOR_TEMP_TOPIC),
        "dhw": (CONF_DHW_TOP_TOPIC, CONF_DHW_BOTTOM_TOPIC, CONF_DHW_VALVE_TOPIC),
        "buffer_heater": ("buffer_heater_command_topic", "buffer_heater_state_topic"),
        "dhw_heater": ("dhw_heater_command_topic", "dhw_heater_state_topic"),
        "power": (CONF_HP_POWER_TOPIC,),
    }
    for key in topic_keys.get(step, ()):
        if not _valid_input_topic(data.get(key)):
            errors[key] = "invalid_input_topic"
    if step in ("buffer_heater", "dhw_heater"):
        prefix = step.replace("_heater", "")
        if not parse_steps(data.get(f"{prefix}_heater_steps_kw")):
            errors[f"{prefix}_heater_steps_kw"] = "invalid_steps"
        max_t = str(data.get(f"{prefix}_heater_max_temperature") or "").strip()
        if max_t:
            try:
                float(max_t.replace(",", "."))
            except ValueError:
                errors[f"{prefix}_heater_max_temperature"] = "invalid_number"
    if step == "dhw":
        if not parse_times(data.get(CONF_DHW_READY_TIMES)) and str(data.get(CONF_DHW_READY_TIMES) or "").strip():
            errors[CONF_DHW_READY_TIMES] = "invalid_times"
        if float(data.get(CONF_DHW_MIN_T, 0)) >= float(data.get(CONF_DHW_MAX_T, 100)):
            errors[CONF_DHW_MAX_T] = "invalid_temperature_range"
    if step == "tariff":
        for key in (CONF_DIST_OFFPEAK_HOURS, CONF_DIST_PEAK2_HOURS):
            text = str(data.get(key) or "").strip()
            if text and not parse_hour_ranges(text):
                errors[key] = "invalid_hours"
    if step == "notifications":
        service = str(data.get(CONF_NOTIFY_SERVICE) or "").strip()
        if service and not service.startswith("notify."):
            errors[CONF_NOTIFY_SERVICE] = "invalid_notify_service"
    if step == "mqtt":
        prefix = str(data.get(CONF_MQTT_PREFIX, "")).strip()
        if not prefix or "#" in prefix or "+" in prefix:
            errors[CONF_MQTT_PREFIX] = "invalid_prefix"
    if (
        step == "market"
        and data.get(CONF_MARKET_PROVIDER) == MARKET_PROVIDER_ENTSOE
        and not data.get(CONF_ENTSOE_TOKEN)
    ):
        errors[CONF_ENTSOE_TOKEN] = "entsoe_token_required"
    return errors


def _normalise(step: str, data: dict[str, Any]) -> dict[str, Any]:
    out = dict(data)
    text_keys = {
        "buffer": BUFFER_TEXT_KEYS + BUFFER_ENTITY_KEYS,
        "dhw": (*DHW_TEXT_KEYS, CONF_DHW_TOP_ENTITY, CONF_DHW_BOTTOM_ENTITY),
        "buffer_heater": tuple(
            f"buffer_heater_{f}" for f in ("max_temperature", "command_topic", "state_topic", "state_json_key")
        ),
        "dhw_heater": tuple(
            f"dhw_heater_{f}" for f in ("max_temperature", "command_topic", "state_topic", "state_json_key")
        ),
        "power": (*POWER_TEXT_KEYS, CONF_HP_POWER_ENTITY),
        "tariff": (CONF_DIST_OFFPEAK_HOURS, CONF_DIST_PEAK2_HOURS),
        "notifications": (CONF_NOTIFY_SERVICE,),
    }
    # cleared optional text fields are omitted by the frontend -> store as "not set"
    for key in text_keys.get(step, ()):
        out[key] = str(out.get(key) or "").strip()
    if step == "buffer":
        out[CONF_INPUT_MAX_AGE_MIN] = int(out.get(CONF_INPUT_MAX_AGE_MIN, DEFAULT_INPUT_MAX_AGE_MIN))
    if CONF_MQTT_QOS in out:
        out[CONF_MQTT_QOS] = int(out[CONF_MQTT_QOS])
    for key in (
        CONF_CHEAP_HOURS,
        CONF_FORECAST_HORIZON_H,
        CONF_HISTORY_DAYS,
        CONF_WEATHER_REFRESH_H,
        CONF_MIN_RUNTIME_H,
        CONF_MIN_OFFTIME_H,
        CONF_MAX_STARTS,
        CONF_MAX_SPECULATIVE_H,
    ):
        if key in out:
            out[key] = int(out[key])
    if step == "mqtt" and CONF_MQTT_PREFIX in out:
        out[CONF_MQTT_PREFIX] = str(out[CONF_MQTT_PREFIX]).strip().strip("/")
    return out


STEPS = ["location", "market", "weather", "forecast", "optimization", "buffer", "mqtt"]
OPTION_MENU = [
    "pstryk",
    "tariff",
    "location",
    "market",
    "weather",
    "forecast",
    "optimization",
    "buffer",
    "buffer_heater",
    "dhw",
    "dhw_heater",
    "power",
    "pv",
    "learning",
    "notifications",
    "mqtt",
    "mqtt_topics",
    "panel",
]


def schema_topics(overrides: Mapping[str, str]) -> vol.Schema:
    """One text field per MQTT topic; an emptied field disables that topic."""
    fields: dict[Any, Any] = {}
    for canonical in TOPICS:
        current = overrides.get(canonical, canonical)
        fields[vol.Optional(topic_field(canonical), description={"suggested_value": current})] = selector.TextSelector()
    return vol.Schema(fields)


def parse_topics(prefix: str, user_input: Mapping[str, Any]) -> tuple[dict[str, str], dict[str, str]]:
    """Return (overrides, errors). Only values that differ from the default are stored."""
    overrides: dict[str, str] = {}
    errors: dict[str, str] = {}
    seen: dict[str, str] = {}
    for canonical in TOPICS:
        field = topic_field(canonical)
        value = str(user_input.get(field) or "").strip()
        if not validate_topic(value):
            errors[field] = "invalid_topic"
            continue
        if value != canonical:
            overrides[canonical] = value
        full = resolve_topic(prefix, canonical, overrides)
        if full is None:
            continue
        if full in seen:
            errors[field] = "duplicate_topic"
        seen[full] = canonical
    return overrides, errors


def schema_panel(v: Mapping[str, Any]) -> vol.Schema:
    return vol.Schema({vol.Required(CONF_SHOW_PANEL, default=_d(v, CONF_SHOW_PANEL, True)): bool})


class PstrykAIConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1
    MINOR_VERSION = 2

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._checks: dict[str, str] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            await self.async_set_unique_id(key_fingerprint(api_key))
            self._abort_if_unique_id_configured()
            errors = await self._test_pstryk(api_key)
            if not errors:
                self._data.update(user_input)
                self._data[CONF_API_KEY] = api_key
                return await self.async_step_location()
        return self.async_show_form(step_id="user", data_schema=schema_pstryk(user_input or {}, True), errors=errors)

    async def _test_pstryk(self, api_key: str) -> dict[str, str]:
        client = PstrykClient(async_get_clientsession(self.hass), api_key)
        try:
            await client.validate(dt_util.utcnow())
        except ProviderAuthError:
            return {"base": "invalid_auth"}
        except ProviderNotFound:
            return {"base": "no_contract"}
        except ProviderRateLimited:
            return {"base": "rate_limited"}
        except ProviderError as err:
            _LOGGER.debug("Pstryk validation failed: %s", err)
            return {"base": "cannot_connect"}
        return {}

    async def _section(
        self, step: str, user_input: dict[str, Any] | None, schema: vol.Schema, next_step
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = validate_section(step, user_input)
            if not errors:
                self._data.update(_normalise(step, user_input))
                return await next_step()
        return self.async_show_form(step_id=step, data_schema=schema, errors=errors)

    async def async_step_location(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._section(
            "location",
            user_input,
            schema_location(self._data, self.hass.config.latitude, self.hass.config.longitude),
            self.async_step_market,
        )

    async def async_step_market(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None and user_input.get(CONF_ENTSOE_TOKEN):
            client = EntsoeClient(async_get_clientsession(self.hass), user_input[CONF_ENTSOE_TOKEN], 4.25)
            try:
                now = dt_util.utcnow()
                await client.fetch_day_ahead(now - timedelta(days=1), now)
            except ProviderAuthError:
                return self.async_show_form(
                    step_id="market",
                    data_schema=schema_market(user_input),
                    errors={CONF_ENTSOE_TOKEN: "invalid_entsoe"},
                )
            except ProviderError:
                self._checks["entsoe"] = "error"
            else:
                self._checks["entsoe"] = "ok"
        return await self._section(
            "market", user_input, schema_market(user_input or self._data), self.async_step_weather
        )

    async def async_step_weather(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._section("weather", user_input, schema_weather(self._data), self.async_step_forecast)

    async def async_step_forecast(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._section("forecast", user_input, schema_forecast(self._data), self.async_step_optimization)

    async def async_step_optimization(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._section(
            "optimization", user_input, schema_optimization(user_input or self._data), self.async_step_buffer
        )

    async def async_step_buffer(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._section("buffer", user_input, schema_buffer(user_input or self._data), self.async_step_mqtt)

    async def async_step_mqtt(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._section("mqtt", user_input, schema_mqtt(user_input or self._data), self.async_step_validate)

    async def async_step_validate(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is None:
            await self._run_checks()
            return self.async_show_form(
                step_id="validate",
                data_schema=vol.Schema({}),
                description_placeholders={"results": "\n".join(f"- {k}: {v}" for k, v in self._checks.items())},
            )
        data = {CONF_API_KEY: self._data.pop(CONF_API_KEY)}
        if self._data.get(CONF_ENTSOE_TOKEN):
            data[CONF_ENTSOE_TOKEN] = self._data.pop(CONF_ENTSOE_TOKEN)
        else:
            self._data.pop(CONF_ENTSOE_TOKEN, None)
        return self.async_create_entry(title=NAME, data=data, options=self._data)

    async def _run_checks(self) -> None:
        session = async_get_clientsession(self.hass)
        self._checks["pstryk"] = "ok"
        today = date.today()
        try:
            rows = await PseClient(session).system_forecast(today, today + timedelta(days=1))
            self._checks["pse"] = f"ok ({len(rows)} h)"
        except ProviderError as err:
            self._checks["pse"] = f"error: {err}"[:60]
        lat = self.hass.config.latitude if self._data.get(CONF_USE_HA_LOCATION, True) else self._data.get(CONF_LATITUDE)
        lon = (
            self.hass.config.longitude if self._data.get(CONF_USE_HA_LOCATION, True) else self._data.get(CONF_LONGITUDE)
        )
        try:
            rows = await WeatherClient(
                session, self._data.get(CONF_WEATHER_MODEL, DEFAULT_WEATHER_MODEL)
            ).local_forecast(float(lat), float(lon))
            self._checks["open-meteo"] = f"ok ({len(rows)} h)"
        except ProviderError as err:
            self._checks["open-meteo"] = f"error: {err}"[:60]
        if self._data.get(CONF_MQTT_ENABLED, True):
            self._checks["mqtt"] = "ok" if "mqtt" in self.hass.config.components else "not_configured"
        self._checks.setdefault("entsoe", "skipped" if not self._data.get(CONF_ENTSOE_TOKEN) else "ok")
        self._checks["forecast"] = "baseline_ready_after_history_import"

    # ------------------------------------------------------------ reauth
    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            api_key = user_input[CONF_API_KEY].strip()
            errors = await self._test_pstryk(api_key)
            if not errors:
                entry = self._get_reauth_entry()
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_API_KEY: api_key}, unique_id=key_fingerprint(api_key)
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_API_KEY): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.PASSWORD)
                    )
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return PstrykAIOptionsFlow()


class PstrykAIOptionsFlow(OptionsFlow):
    """All options remain editable after setup (menu of sections)."""

    def _values(self) -> dict[str, Any]:
        return {**self.config_entry.data, **self.config_entry.options}

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=OPTION_MENU)

    async def _save(self, step: str, user_input: dict[str, Any] | None, schema: vol.Schema) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = validate_section(step, user_input)
            if not errors:
                options = {**self.config_entry.options, **_normalise(step, user_input)}
                if CONF_ENTSOE_TOKEN in options:
                    token = options.pop(CONF_ENTSOE_TOKEN)
                    data = dict(self.config_entry.data)
                    if token:
                        data[CONF_ENTSOE_TOKEN] = token
                    else:
                        data.pop(CONF_ENTSOE_TOKEN, None)
                    self.hass.config_entries.async_update_entry(self.config_entry, data=data)
                return self.async_create_entry(data=options)
        return self.async_show_form(step_id=step, data_schema=schema, errors=errors)

    async def async_step_pstryk(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._save("pstryk", user_input, schema_pstryk(self._values(), False))

    async def async_step_location(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._save(
            "location",
            user_input,
            schema_location(self._values(), self.hass.config.latitude, self.hass.config.longitude),
        )

    async def async_step_market(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._save("market", user_input, schema_market(self._values()))

    async def async_step_weather(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._save("weather", user_input, schema_weather(self._values()))

    async def async_step_forecast(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._save("forecast", user_input, schema_forecast(self._values()))

    async def async_step_optimization(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._save("optimization", user_input, schema_optimization(self._values()))

    async def async_step_buffer(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._save("buffer", user_input, schema_buffer(self._values()))

    async def async_step_mqtt(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._save("mqtt", user_input, schema_mqtt(self._values()))

    async def async_step_mqtt_topics(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        values = self._values()
        current = dict(values.get(CONF_MQTT_TOPICS) or {})
        prefix = str(values.get(CONF_MQTT_PREFIX) or DEFAULT_MQTT_PREFIX)
        errors: dict[str, str] = {}
        if user_input is not None:
            overrides, errors = parse_topics(prefix, user_input)
            if not errors:
                return self.async_create_entry(data={**self.config_entry.options, CONF_MQTT_TOPICS: overrides})
            current = {c: str(user_input.get(topic_field(c)) or "") for c in TOPICS}
        return self.async_show_form(
            step_id="mqtt_topics",
            data_schema=schema_topics(current),
            errors=errors,
            description_placeholders={"prefix": prefix},
        )

    async def async_step_panel(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._save("panel", user_input, schema_panel(self._values()))

    async def async_step_tariff(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._save("tariff", user_input, schema_tariff(self._values()))

    async def async_step_buffer_heater(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._save("buffer_heater", user_input, schema_heater(self._values(), "buffer"))

    async def async_step_dhw(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._save("dhw", user_input, schema_dhw(self._values()))

    async def async_step_dhw_heater(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._save("dhw_heater", user_input, schema_heater(self._values(), "dhw"))

    async def async_step_power(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._save("power", user_input, schema_power(self._values()))

    async def async_step_pv(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._save("pv", user_input, schema_pv(self._values()))

    async def async_step_learning(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._save("learning", user_input, schema_learning(self._values()))

    async def async_step_notifications(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._save("notifications", user_input, schema_notifications(self._values()))
