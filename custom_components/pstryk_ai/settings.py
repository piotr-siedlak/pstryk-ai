"""Typed view of config entry data + options."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    BUFFER_STRATEGY_COST,
    CONF_ADVISORY_MODE,
    CONF_API_KEY,
    CONF_AUTO_CALIBRATE_TARIFF,
    CONF_AUTO_RETRAIN,
    CONF_BUFFER_ENABLED,
    CONF_BUFFER_MAX_T,
    CONF_BUFFER_MIN_T,
    CONF_BUFFER_STRATEGY,
    CONF_BUFFER_TARGET_T,
    CONF_BUFFER_TEMP_ENTITY,
    CONF_BUFFER_TEMP_KEY,
    CONF_BUFFER_TEMP_TOPIC,
    CONF_BUFFER_TOP_ENTITY,
    CONF_BUFFER_TOP_KEY,
    CONF_BUFFER_TOP_TOPIC,
    CONF_BUFFER_VOLUME_L,
    CONF_CHEAP_HOURS,
    CONF_DEVICE_PROFILES,
    CONF_ENERGY_MARGIN,
    CONF_ENTSOE_TOKEN,
    CONF_EUR_PLN,
    CONF_EXCISE,
    CONF_FORECAST_HORIZON_H,
    CONF_FORECAST_MODEL,
    CONF_HEAT_LOSS_COEFF,
    CONF_HISTORY_DAYS,
    CONF_HP_COP,
    CONF_HP_COP_CURVE,
    CONF_HP_ELECTRIC_KW,
    CONF_HP_THERMAL_KW,
    CONF_INDOOR_BASE_T,
    CONF_INPUT_MAX_AGE_MIN,
    CONF_LATITUDE,
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
    CONF_OPTIMIZATION_ENABLED,
    CONF_OUTDOOR_TEMP_ENTITY,
    CONF_OUTDOOR_TEMP_KEY,
    CONF_OUTDOOR_TEMP_TOPIC,
    CONF_PRICE_INCLUDES_DISTRIBUTION,
    CONF_PRICE_THRESHOLD,
    CONF_PROSUMER,
    CONF_PSE_ENABLED,
    CONF_RISK_AVERSION,
    CONF_SHOW_PANEL,
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
    FORECAST_MODEL_AUTO,
    MARKET_PROVIDER_ENTSOE,
    MARKET_PROVIDER_PSE_RCE,
)
from .models.optimizer import DeviceProfile
from .optimization.heat_pump import CopModel, parse_cop_curve
from .optimization.thermal_storage import BufferConfig
from .settings_ext import ExtSettings, load_ext
from .tariff import Tariff

_LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class Settings:
    api_key: str
    latitude: float
    longitude: float
    entsoe_token: str | None
    prosumer: bool
    market_provider: str
    tge_enabled: bool
    pse_enabled: bool
    eur_pln: float
    weather_model: str
    weather_refresh_h: int
    history_days: int
    horizon_h: int
    forecast_model: str
    auto_retrain: bool
    risk_aversion: float
    max_speculative_h: int
    tariff: Tariff
    auto_calibrate: bool
    cheap_hours: int
    price_threshold: float
    profiles: list[DeviceProfile]
    buffer_enabled: bool
    buffer_temp_entity: str | None
    outdoor_temp_entity: str | None
    buffer_temp_topic: str | None
    buffer_temp_key: str | None
    outdoor_temp_topic: str | None
    outdoor_temp_key: str | None
    input_max_age_min: int
    buffer: BufferConfig
    cop: CopModel
    buffer_strategy: str
    mqtt_enabled: bool
    mqtt_prefix: str
    mqtt_discovery: bool
    mqtt_qos: int
    mqtt_retain: bool
    mqtt_evcc: bool
    mqtt_topics: dict[str, str]
    show_panel: bool
    optimization_enabled: bool
    advisory_mode: bool
    ext: ExtSettings = field(default_factory=ExtSettings)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def effective_market_provider(self) -> str:
        if self.market_provider == MARKET_PROVIDER_ENTSOE and not self.entsoe_token:
            return MARKET_PROVIDER_PSE_RCE
        return self.market_provider


def parse_profiles(value: Any) -> list[DeviceProfile]:
    if not value:
        return []
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            _LOGGER.warning("Device profiles are not valid JSON; ignoring")
            return []
    out = []
    for item in value if isinstance(value, list) else []:
        try:
            out.append(DeviceProfile.from_dict(item))
        except (KeyError, TypeError, ValueError) as err:
            _LOGGER.warning("Invalid device profile %s: %s", item, err)
    return out


def load_settings(hass: HomeAssistant, entry: ConfigEntry) -> Settings:
    c: dict[str, Any] = {**entry.data, **entry.options}

    def g(key: str, default: Any) -> Any:
        value = c.get(key)
        return default if value is None or value == "" else value

    use_ha = g(CONF_USE_HA_LOCATION, True)
    lat = float(hass.config.latitude if use_ha else g(CONF_LATITUDE, hass.config.latitude))
    lon = float(hass.config.longitude if use_ha else g(CONF_LONGITUDE, hass.config.longitude))
    min_t = float(g(CONF_BUFFER_MIN_T, DEFAULT_BUFFER_MIN_T))
    max_t = float(g(CONF_BUFFER_MAX_T, DEFAULT_BUFFER_MAX_T))
    strategy = g(CONF_BUFFER_STRATEGY, BUFFER_STRATEGY_COST)
    ext = load_ext(c)
    tariff = Tariff(
        vat_rate=float(g(CONF_VAT_RATE, DEFAULT_VAT_RATE)),
        energy_margin_net=float(g(CONF_ENERGY_MARGIN, DEFAULT_ENERGY_MARGIN)),
        excise_net=float(g(CONF_EXCISE, DEFAULT_EXCISE)),
        var_distribution_net=float(g(CONF_VAR_DISTRIBUTION, DEFAULT_VAR_DISTRIBUTION)),
        pstryk_includes_distribution=bool(g(CONF_PRICE_INCLUDES_DISTRIBUTION, False)),
        distribution=ext.distribution,
    )
    return Settings(
        api_key=c[CONF_API_KEY],
        latitude=lat,
        longitude=lon,
        entsoe_token=g(CONF_ENTSOE_TOKEN, None),
        prosumer=bool(g(CONF_PROSUMER, False)),
        market_provider=g(CONF_MARKET_PROVIDER, MARKET_PROVIDER_ENTSOE),
        tge_enabled=bool(g(CONF_TGE_ENABLED, False)),
        pse_enabled=bool(g(CONF_PSE_ENABLED, True)),
        eur_pln=float(g(CONF_EUR_PLN, DEFAULT_EUR_PLN)),
        weather_model=g(CONF_WEATHER_MODEL, DEFAULT_WEATHER_MODEL),
        weather_refresh_h=int(g(CONF_WEATHER_REFRESH_H, DEFAULT_WEATHER_REFRESH_H)),
        history_days=int(g(CONF_HISTORY_DAYS, DEFAULT_HISTORY_DAYS)),
        horizon_h=int(g(CONF_FORECAST_HORIZON_H, DEFAULT_HORIZON_H)),
        forecast_model=g(CONF_FORECAST_MODEL, FORECAST_MODEL_AUTO),
        auto_retrain=bool(g(CONF_AUTO_RETRAIN, True)),
        risk_aversion=float(g(CONF_RISK_AVERSION, DEFAULT_RISK_AVERSION)),
        max_speculative_h=int(g(CONF_MAX_SPECULATIVE_H, DEFAULT_MAX_SPECULATIVE_H)),
        tariff=tariff,
        auto_calibrate=bool(g(CONF_AUTO_CALIBRATE_TARIFF, False)),
        cheap_hours=int(g(CONF_CHEAP_HOURS, DEFAULT_CHEAP_HOURS)),
        price_threshold=float(g(CONF_PRICE_THRESHOLD, DEFAULT_PRICE_THRESHOLD)),
        profiles=parse_profiles(c.get(CONF_DEVICE_PROFILES)),
        buffer_enabled=bool(g(CONF_BUFFER_ENABLED, False)),
        buffer_temp_entity=g(CONF_BUFFER_TOP_ENTITY, None) or g(CONF_BUFFER_TEMP_ENTITY, None),
        outdoor_temp_entity=g(CONF_OUTDOOR_TEMP_ENTITY, None),
        buffer_temp_topic=(str(g(CONF_BUFFER_TOP_TOPIC, "") or g(CONF_BUFFER_TEMP_TOPIC, "")).strip() or None),
        buffer_temp_key=(str(g(CONF_BUFFER_TOP_KEY, "") or g(CONF_BUFFER_TEMP_KEY, "")).strip() or None),
        outdoor_temp_topic=(str(g(CONF_OUTDOOR_TEMP_TOPIC, "")).strip() or None),
        outdoor_temp_key=(str(g(CONF_OUTDOOR_TEMP_KEY, "")).strip() or None),
        input_max_age_min=int(g(CONF_INPUT_MAX_AGE_MIN, DEFAULT_INPUT_MAX_AGE_MIN)),
        buffer=BufferConfig(
            volume_l=float(g(CONF_BUFFER_VOLUME_L, DEFAULT_BUFFER_VOLUME_L)),
            min_t=min_t,
            max_t=max(max_t, min_t + 1),
            target_t=float(g(CONF_BUFFER_TARGET_T, DEFAULT_BUFFER_TARGET_T)),
            hp_thermal_kw=float(g(CONF_HP_THERMAL_KW, DEFAULT_HP_THERMAL_KW)),
            hp_electric_kw=float(g(CONF_HP_ELECTRIC_KW, DEFAULT_HP_ELECTRIC_KW)),
            loss_kw_per_k=float(g(CONF_THERMAL_LOSS_KW_K, DEFAULT_THERMAL_LOSS_KW_K)),
            building_kw_per_k=float(g(CONF_HEAT_LOSS_COEFF, DEFAULT_HEAT_LOSS_COEFF)),
            base_t=float(g(CONF_INDOOR_BASE_T, DEFAULT_INDOOR_BASE_T)),
            min_runtime_h=int(g(CONF_MIN_RUNTIME_H, DEFAULT_MIN_RUNTIME_H)),
            min_offtime_h=int(g(CONF_MIN_OFFTIME_H, DEFAULT_MIN_OFFTIME_H)),
            max_starts_per_day=int(g(CONF_MAX_STARTS, DEFAULT_MAX_STARTS)),
            comfort_penalty_pln_per_kh=20.0 if strategy != BUFFER_STRATEGY_COST else 5.0,
            risk_aversion=float(g(CONF_RISK_AVERSION, DEFAULT_RISK_AVERSION)),
            name="buffer",
            hp_max_t=ext.hp_max_t,
            heater=ext.buffer_heater.config if ext.buffer_heater.enabled else None,
        ),
        cop=CopModel(
            nominal_cop=float(g(CONF_HP_COP, DEFAULT_HP_COP)),
            curve=parse_cop_curve(c.get(CONF_HP_COP_CURVE)),
        ),
        buffer_strategy=strategy,
        mqtt_enabled=bool(g(CONF_MQTT_ENABLED, True)),
        mqtt_prefix=str(g(CONF_MQTT_PREFIX, DEFAULT_MQTT_PREFIX)),
        mqtt_discovery=bool(g(CONF_MQTT_DISCOVERY, False)),
        mqtt_qos=int(g(CONF_MQTT_QOS, DEFAULT_MQTT_QOS)),
        mqtt_retain=bool(g(CONF_MQTT_RETAIN, True)),
        mqtt_evcc=bool(g(CONF_MQTT_EVCC, False)),
        mqtt_topics={str(k): str(v) for k, v in (c.get(CONF_MQTT_TOPICS) or {}).items()},
        show_panel=bool(g(CONF_SHOW_PANEL, True)),
        optimization_enabled=bool(g(CONF_OPTIMIZATION_ENABLED, True)),
        advisory_mode=bool(g(CONF_ADVISORY_MODE, True)),
        ext=ext,
        raw=c,
    )
