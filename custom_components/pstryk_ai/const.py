"""Constants for the Pstryk AI integration."""

from __future__ import annotations

from typing import Final

DOMAIN: Final = "pstryk_ai"
NAME: Final = "Pstryk AI"
MANUFACTURER: Final = "Pstryk AI (community)"
VERSION: Final = "0.3.0"

LOCAL_TZ: Final = "Europe/Warsaw"

# ---------------------------------------------------------------------------
# Config entry keys (data)
# ---------------------------------------------------------------------------
CONF_API_KEY: Final = "api_key"
CONF_LATITUDE: Final = "latitude"
CONF_LONGITUDE: Final = "longitude"
CONF_USE_HA_LOCATION: Final = "use_ha_location"
CONF_ENTSOE_TOKEN: Final = "entsoe_token"

# ---------------------------------------------------------------------------
# Options keys
# ---------------------------------------------------------------------------
CONF_PROSUMER: Final = "prosumer"
CONF_MARKET_PROVIDER: Final = "market_provider"
CONF_TGE_ENABLED: Final = "tge_enabled"
CONF_PSE_ENABLED: Final = "pse_enabled"
CONF_EUR_PLN: Final = "eur_pln_rate"

CONF_WEATHER_MODEL: Final = "weather_model"
CONF_WEATHER_REFRESH_H: Final = "weather_refresh_hours"
CONF_HISTORY_DAYS: Final = "history_days"

CONF_FORECAST_HORIZON_H: Final = "forecast_horizon_hours"
CONF_FORECAST_MODEL: Final = "forecast_model"
CONF_AUTO_RETRAIN: Final = "auto_retrain"
CONF_RISK_AVERSION: Final = "risk_aversion"
CONF_MAX_SPECULATIVE_H: Final = "max_speculative_hours"

# Tariff (all values net PLN/kWh unless stated otherwise)
CONF_VAT_RATE: Final = "vat_rate"
CONF_ENERGY_MARGIN: Final = "energy_margin_net"
CONF_EXCISE: Final = "excise_net"
CONF_VAR_DISTRIBUTION: Final = "var_distribution_net"
CONF_PRICE_INCLUDES_DISTRIBUTION: Final = "pstryk_price_includes_distribution"
CONF_AUTO_CALIBRATE_TARIFF: Final = "auto_calibrate_tariff"

CONF_CHEAP_HOURS: Final = "cheap_hours_count"
CONF_PRICE_THRESHOLD: Final = "price_threshold"
CONF_DEVICE_PROFILES: Final = "device_profiles"

# Thermal buffer
CONF_BUFFER_ENABLED: Final = "buffer_enabled"
CONF_BUFFER_TEMP_ENTITY: Final = "buffer_temperature_entity"
CONF_OUTDOOR_TEMP_ENTITY: Final = "outdoor_temperature_entity"
CONF_BUFFER_TEMP_TOPIC: Final = "buffer_temperature_topic"
CONF_BUFFER_TEMP_KEY: Final = "buffer_temperature_json_key"
CONF_OUTDOOR_TEMP_TOPIC: Final = "outdoor_temperature_topic"
CONF_OUTDOOR_TEMP_KEY: Final = "outdoor_temperature_json_key"
CONF_INPUT_MAX_AGE_MIN: Final = "mqtt_input_max_age_minutes"
CONF_BUFFER_VOLUME_L: Final = "buffer_capacity_liters"
CONF_BUFFER_MIN_T: Final = "buffer_min_temperature"
CONF_BUFFER_MAX_T: Final = "buffer_max_temperature"
CONF_BUFFER_TARGET_T: Final = "buffer_target_temperature"
CONF_HP_ELECTRIC_KW: Final = "heat_pump_electrical_power"
CONF_HP_THERMAL_KW: Final = "heat_pump_thermal_power"
CONF_HP_COP: Final = "heat_pump_cop"
CONF_HP_COP_CURVE: Final = "heat_pump_cop_curve"
CONF_THERMAL_LOSS_KW_K: Final = "thermal_losses"
CONF_HEAT_LOSS_COEFF: Final = "building_heat_loss_kw_per_k"
CONF_INDOOR_BASE_T: Final = "heating_base_temperature"
CONF_MIN_RUNTIME_H: Final = "minimum_runtime"
CONF_MIN_OFFTIME_H: Final = "minimum_offtime"
CONF_MAX_STARTS: Final = "maximum_start_count"
CONF_BUFFER_STRATEGY: Final = "buffer_strategy"

# MQTT
CONF_MQTT_ENABLED: Final = "mqtt_enabled"
CONF_MQTT_PREFIX: Final = "mqtt_prefix"
CONF_MQTT_DISCOVERY: Final = "mqtt_discovery"
CONF_MQTT_QOS: Final = "mqtt_qos"
CONF_MQTT_RETAIN: Final = "mqtt_retain"
CONF_MQTT_EVCC: Final = "mqtt_evcc"
CONF_MQTT_TOPICS: Final = "mqtt_topics"
CONF_SHOW_PANEL: Final = "show_panel"

# Runtime switches (persisted in options)
CONF_OPTIMIZATION_ENABLED: Final = "optimization_enabled"
CONF_ADVISORY_MODE: Final = "advisory_mode"

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------
DEFAULT_MQTT_PREFIX: Final = "pstryk_ai/home"
DEFAULT_MQTT_QOS: Final = 1
DEFAULT_VAT_RATE: Final = 0.23
DEFAULT_ENERGY_MARGIN: Final = 0.0
DEFAULT_EXCISE: Final = 0.005
DEFAULT_VAR_DISTRIBUTION: Final = 0.0
DEFAULT_EUR_PLN: Final = 4.25
DEFAULT_HORIZON_H: Final = 168
DEFAULT_HISTORY_DAYS: Final = 365
DEFAULT_WEATHER_REFRESH_H: Final = 6
DEFAULT_CHEAP_HOURS: Final = 6
DEFAULT_PRICE_THRESHOLD: Final = 0.5
DEFAULT_RISK_AVERSION: Final = 0.3
DEFAULT_MAX_SPECULATIVE_H: Final = 72

DEFAULT_BUFFER_VOLUME_L: Final = 500
DEFAULT_BUFFER_MIN_T: Final = 30.0
DEFAULT_BUFFER_MAX_T: Final = 55.0
DEFAULT_BUFFER_TARGET_T: Final = 40.0
DEFAULT_HP_ELECTRIC_KW: Final = 3.0
DEFAULT_HP_THERMAL_KW: Final = 9.0
DEFAULT_HP_COP: Final = 3.0
DEFAULT_THERMAL_LOSS_KW_K: Final = 0.003
DEFAULT_HEAT_LOSS_COEFF: Final = 0.25
DEFAULT_INDOOR_BASE_T: Final = 18.0
DEFAULT_MIN_RUNTIME_H: Final = 1
DEFAULT_MIN_OFFTIME_H: Final = 1
DEFAULT_MAX_STARTS: Final = 6
DEFAULT_INPUT_MAX_AGE_MIN: Final = 30

MARKET_PROVIDER_ENTSOE: Final = "entsoe"
MARKET_PROVIDER_TGE: Final = "tge"
MARKET_PROVIDER_PSE_RCE: Final = "pse_rce"
MARKET_PROVIDERS: Final = [MARKET_PROVIDER_ENTSOE, MARKET_PROVIDER_TGE, MARKET_PROVIDER_PSE_RCE]

WEATHER_MODELS: Final = ["ecmwf_ifs025", "icon_seamless", "gfs_seamless", "best_match"]
DEFAULT_WEATHER_MODEL: Final = "ecmwf_ifs025"

FORECAST_MODEL_AUTO: Final = "auto"
FORECAST_MODEL_BASELINE: Final = "baseline"
FORECAST_MODEL_RIDGE: Final = "ridge"
FORECAST_MODELS: Final = [FORECAST_MODEL_AUTO, FORECAST_MODEL_BASELINE, FORECAST_MODEL_RIDGE]

BUFFER_STRATEGY_COST: Final = "min_cost"
BUFFER_STRATEGY_COMFORT: Final = "comfort"
BUFFER_STRATEGIES: Final = [BUFFER_STRATEGY_COST, BUFFER_STRATEGY_COMFORT]

# ---------------------------------------------------------------------------
# Pstryk API
# ---------------------------------------------------------------------------
PSTRYK_BASE_URL: Final = "https://api.pstryk.pl/integrations/"
PSTRYK_UNIFIED_PATH: Final = "meter-data/unified-metrics/"
# Official terms: 3 requests/hour for "heavy" endpoints. We budget less than
# that and share the budget per API key across all config entries.
PSTRYK_BUDGET_PER_HOUR: Final = 2
PSTRYK_BUDGET_WINDOW_S: Final = 3600

# ---------------------------------------------------------------------------
# Events / services
# ---------------------------------------------------------------------------
EVENT_PRICES_CONFIRMED: Final = f"{DOMAIN}_prices_confirmed"
EVENT_PLAN_UPDATED: Final = f"{DOMAIN}_plan_updated"

SERVICE_RECALCULATE_FORECAST: Final = "recalculate_forecast"
SERVICE_RECALCULATE_SCHEDULE: Final = "recalculate_schedule"
SERVICE_RETRAIN_MODEL: Final = "retrain_model"
SERVICE_IMPORT_HISTORY: Final = "import_history"
SERVICE_RUN_BACKTEST: Final = "run_backtest"

STORAGE_VERSION: Final = 1
