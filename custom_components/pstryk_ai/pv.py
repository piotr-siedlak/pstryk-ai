"""PV self-consumption: production forecast and surplus per hour.

Production ≈ kWp · GHI/1000 · performance ratio, using the Open-Meteo shortwave
radiation of the building location. Surplus = production − base household load.
Flexible loads (heat pump, heaters, devices) value surplus energy at the Pstryk
sell price instead of the buy price, because that energy would otherwise be
exported.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .api.weather import WeatherHour
from .models.price_slot import PriceSlot


@dataclass(slots=True)
class PvConfig:
    kwp: float = 5.0
    performance_ratio: float = 0.8
    base_load_kw: float = 0.4


def pv_forecast(weather: Iterable[WeatherHour], cfg: PvConfig) -> dict[datetime, float]:
    """kWh produced per hour (hour-start UTC key)."""
    out: dict[datetime, float] = {}
    for w in weather:
        ghi = w.get("shortwave_radiation")
        if ghi is None:
            continue
        out[w.start] = max(0.0, cfg.kwp * float(ghi) / 1000.0 * cfg.performance_ratio)
    return out


def surplus(production: dict[datetime, float], cfg: PvConfig) -> dict[datetime, float]:
    return {t: max(0.0, kwh - cfg.base_load_kw) for t, kwh in production.items()}


def device_price(slot: PriceSlot, sell: float | None, surplus_kwh: float, load_kw: float) -> float | None:
    """Blended price of running ``load_kw`` for one hour with PV surplus available."""
    if slot.value is None:
        return None
    if sell is None or surplus_kwh <= 0 or load_kw <= 0:
        return slot.value
    own = min(load_kw, surplus_kwh)
    return (own * sell + (load_kw - own) * slot.value) / load_kw


def summary(
    production: dict[datetime, float], surplus_map: dict[datetime, float], day_hours: list[datetime]
) -> dict[str, Any]:
    return {
        "production_kwh": round(sum(production.get(h, 0.0) for h in day_hours), 2),
        "surplus_kwh": round(sum(surplus_map.get(h, 0.0) for h in day_hours), 2),
    }
