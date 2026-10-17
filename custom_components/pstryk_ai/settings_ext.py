"""Typed settings for the v0.4 features (all optional, all switchable)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .const import (
    COMMAND_BINARY,
    CONF_BASE_LOAD_KW,
    CONF_BUFFER_BOTTOM_ENTITY,
    CONF_BUFFER_BOTTOM_KEY,
    CONF_BUFFER_BOTTOM_TOPIC,
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
    CONF_HEARTBEAT,
    CONF_HP_MAX_T,
    CONF_HP_POWER_ENTITY,
    CONF_HP_POWER_KEY,
    CONF_HP_POWER_TOPIC,
    CONF_LEARN_APPLY,
    CONF_LEARN_COP,
    CONF_LEARN_DHW_PROFILE,
    CONF_LEARN_LOSSES,
    CONF_LEGIONELLA_DAYS,
    CONF_LEGIONELLA_ENABLED,
    CONF_LEGIONELLA_T,
    CONF_NOTIFY_FALLBACK,
    CONF_NOTIFY_NEGATIVE,
    CONF_NOTIFY_SERVICE,
    CONF_NOTIFY_STALE,
    CONF_NOTIFY_TOMORROW,
    CONF_OPTIMIZE_ALL_IN,
    CONF_POWER_LIMIT_ENABLED,
    CONF_POWER_LIMIT_KW,
    CONF_POWER_UNIT,
    CONF_PV_ENABLED,
    CONF_PV_KWP,
    CONF_PV_PR,
    CONF_SPENDS_ENABLED,
    CONF_SPENDS_HISTORY,
    CONF_STATISTICS_IMPORT,
    DHW_HP_VALVE,
    HEATER_KIND_ELECTRIC,
)
from .optimization.dhw import parse_times
from .optimization.thermal_storage import HeaterConfig
from .pv import PvConfig
from .tariff import (
    DEFAULT_OFFPEAK_HOURS,
    DEFAULT_PEAK2_HOURS,
    DIST_G12W,
    DIST_G13,
    DIST_NONE,
    DistributionTariff,
    parse_hour_ranges,
)


@dataclass(slots=True)
class SensorSource:
    """Where a measurement comes from: an exact MQTT topic and/or an HA entity."""

    topic: str | None = None
    key: str | None = None
    entity: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.topic or self.entity)


@dataclass(slots=True)
class HeaterSettings:
    enabled: bool = False
    config: HeaterConfig = field(default_factory=HeaterConfig)
    command_topic: str | None = None
    command_format: str = COMMAND_BINARY
    state_topic: str | None = None
    state_key: str | None = None


@dataclass(slots=True)
class DhwSettings:
    enabled: bool = False
    top: SensorSource = field(default_factory=SensorSource)
    bottom: SensorSource = field(default_factory=SensorSource)
    volume_l: float = 200.0
    min_t: float = 40.0
    max_t: float = 60.0
    target_t: float = 50.0
    ready_times: list[tuple[int, int]] = field(default_factory=lambda: [(6, 0), (19, 0)])
    ready_t: float = 45.0
    liters_per_day: float = 150.0
    loss_kw_per_k: float = 0.002
    hp_mode: str = DHW_HP_VALVE
    priority: bool = True
    valve_topic: str | None = None
    legionella_enabled: bool = False
    legionella_t: float = 60.0
    legionella_days: int = 7


@dataclass(slots=True)
class ExtSettings:
    buffer_bottom: SensorSource = field(default_factory=SensorSource)
    hp_max_t: float = 55.0
    buffer_heater: HeaterSettings = field(default_factory=HeaterSettings)
    dhw: DhwSettings = field(default_factory=DhwSettings)
    dhw_heater: HeaterSettings = field(default_factory=HeaterSettings)
    power_limit_enabled: bool = False
    power_limit_kw: float = 11.0
    base_load_kw: float = 0.4
    hp_power: SensorSource = field(default_factory=SensorSource)
    power_unit: str = "kW"
    distribution: DistributionTariff | None = None
    optimize_all_in: bool = False
    pv_enabled: bool = False
    pv: PvConfig = field(default_factory=PvConfig)
    learn_losses: bool = False
    learn_dhw_profile: bool = False
    learn_cop: bool = False
    learn_apply: bool = False
    notify: dict[str, bool] = field(default_factory=dict)
    notify_service: str | None = None
    heartbeat: bool = False
    spends: bool = True
    spends_history: bool = True
    statistics_import: bool = False


def _s(c: dict[str, Any], key: str) -> str | None:
    value = c.get(key)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _f(c: dict[str, Any], key: str, default: float) -> float:
    try:
        value = c.get(key)
        return default if value in (None, "") else float(value)
    except (TypeError, ValueError):
        return default


def _b(c: dict[str, Any], key: str, default: bool) -> bool:
    value = c.get(key)
    return default if value is None else bool(value)


def parse_steps(text: Any) -> list[float]:
    out = []
    for part in str(text or "").replace(";", ",").split(","):
        try:
            v = float(part.strip().replace(" ", ""))
        except ValueError:
            continue
        if v > 0:
            out.append(v)
    return sorted(set(out))


def load_heater(c: dict[str, Any], prefix: str) -> HeaterSettings:
    p = f"{prefix}_heater_"
    kind = _s(c, p + "kind") or HEATER_KIND_ELECTRIC
    default_eff = 1.0 if kind == HEATER_KIND_ELECTRIC else 0.92
    max_t = c.get(p + "max_temperature")
    return HeaterSettings(
        enabled=_b(c, p + "enabled", False),
        config=HeaterConfig(
            kind=kind,
            steps_kw=parse_steps(c.get(p + "steps_kw")) or [3.0],
            efficiency=_f(c, p + "efficiency", default_eff),
            fuel_price=_f(c, p + "fuel_price", 0.35),
            max_t=None if max_t in (None, "") else float(max_t),
        ),
        command_topic=_s(c, p + "command_topic"),
        command_format=_s(c, p + "command_format") or COMMAND_BINARY,
        state_topic=_s(c, p + "state_topic"),
        state_key=_s(c, p + "state_json_key"),
    )


def load_ext(c: dict[str, Any]) -> ExtSettings:
    # option values are lowercase (hassfest); accept both spellings
    kind = {"g11": "G11", "g12": "G12", "g12w": "G12w", "g13": "G13", "none": DIST_NONE}.get(
        (_s(c, CONF_DIST_TARIFF) or DIST_NONE).lower(), DIST_NONE
    )
    distribution = None
    if kind != DIST_NONE:
        distribution = DistributionTariff(
            kind=kind,
            rate_peak=_f(c, CONF_DIST_RATE_PEAK, 0.0),
            rate_offpeak=_f(c, CONF_DIST_RATE_OFFPEAK, 0.0),
            rate_peak2=_f(c, CONF_DIST_RATE_PEAK2, 0.0),
            offpeak_hours=parse_hour_ranges(_s(c, CONF_DIST_OFFPEAK_HOURS) or DEFAULT_OFFPEAK_HOURS.get(kind, "")),
            peak2_hours=parse_hour_ranges(_s(c, CONF_DIST_PEAK2_HOURS) or DEFAULT_PEAK2_HOURS.get(kind, "")),
            weekend_offpeak=_b(c, CONF_DIST_WEEKEND_OFFPEAK, kind in (DIST_G12W, DIST_G13)),
        )
    dhw = DhwSettings(
        enabled=_b(c, CONF_DHW_ENABLED, False),
        top=SensorSource(_s(c, CONF_DHW_TOP_TOPIC), _s(c, CONF_DHW_TOP_KEY), _s(c, CONF_DHW_TOP_ENTITY)),
        bottom=SensorSource(_s(c, CONF_DHW_BOTTOM_TOPIC), _s(c, CONF_DHW_BOTTOM_KEY), _s(c, CONF_DHW_BOTTOM_ENTITY)),
        volume_l=_f(c, CONF_DHW_VOLUME_L, 200.0),
        min_t=_f(c, CONF_DHW_MIN_T, 40.0),
        max_t=_f(c, CONF_DHW_MAX_T, 60.0),
        target_t=_f(c, CONF_DHW_TARGET_T, 50.0),
        ready_times=parse_times(_s(c, CONF_DHW_READY_TIMES) or "06:00,19:00"),
        ready_t=_f(c, CONF_DHW_READY_T, 45.0),
        liters_per_day=_f(c, CONF_DHW_LITERS_DAY, 150.0),
        loss_kw_per_k=_f(c, CONF_DHW_LOSS_KW_K, 0.002),
        hp_mode=_s(c, CONF_DHW_HP_MODE) or DHW_HP_VALVE,
        priority=_b(c, CONF_DHW_PRIORITY, True),
        valve_topic=_s(c, CONF_DHW_VALVE_TOPIC),
        legionella_enabled=_b(c, CONF_LEGIONELLA_ENABLED, False),
        legionella_t=_f(c, CONF_LEGIONELLA_T, 60.0),
        legionella_days=int(_f(c, CONF_LEGIONELLA_DAYS, 7)),
    )
    if dhw.max_t <= dhw.min_t:
        dhw.max_t = dhw.min_t + 5
    return ExtSettings(
        buffer_bottom=SensorSource(
            _s(c, CONF_BUFFER_BOTTOM_TOPIC), _s(c, CONF_BUFFER_BOTTOM_KEY), _s(c, CONF_BUFFER_BOTTOM_ENTITY)
        ),
        hp_max_t=_f(c, CONF_HP_MAX_T, 55.0),
        buffer_heater=load_heater(c, "buffer"),
        dhw=dhw,
        dhw_heater=load_heater(c, "dhw"),
        power_limit_enabled=_b(c, CONF_POWER_LIMIT_ENABLED, False),
        power_limit_kw=_f(c, CONF_POWER_LIMIT_KW, 11.0),
        base_load_kw=_f(c, CONF_BASE_LOAD_KW, 0.4),
        hp_power=SensorSource(_s(c, CONF_HP_POWER_TOPIC), _s(c, CONF_HP_POWER_KEY), _s(c, CONF_HP_POWER_ENTITY)),
        power_unit="W" if (_s(c, CONF_POWER_UNIT) or "kW").lower() == "w" else "kW",
        distribution=distribution,
        optimize_all_in=_b(c, CONF_OPTIMIZE_ALL_IN, False),
        pv_enabled=_b(c, CONF_PV_ENABLED, False),
        pv=PvConfig(
            kwp=_f(c, CONF_PV_KWP, 5.0),
            performance_ratio=_f(c, CONF_PV_PR, 0.8),
            base_load_kw=_f(c, CONF_BASE_LOAD_KW, 0.4),
        ),
        learn_losses=_b(c, CONF_LEARN_LOSSES, False),
        learn_dhw_profile=_b(c, CONF_LEARN_DHW_PROFILE, False),
        learn_cop=_b(c, CONF_LEARN_COP, False),
        learn_apply=_b(c, CONF_LEARN_APPLY, False),
        notify={
            "tomorrow_prices": _b(c, CONF_NOTIFY_TOMORROW, False),
            "negative_prices": _b(c, CONF_NOTIFY_NEGATIVE, False),
            "local_control": _b(c, CONF_NOTIFY_FALLBACK, False),
            "stale_data": _b(c, CONF_NOTIFY_STALE, False),
        },
        notify_service=_s(c, CONF_NOTIFY_SERVICE),
        heartbeat=_b(c, CONF_HEARTBEAT, False),
        spends=_b(c, CONF_SPENDS_ENABLED, True),
        spends_history=_b(c, CONF_SPENDS_HISTORY, True),
        statistics_import=_b(c, CONF_STATISTICS_IMPORT, False),
    )
