"""Open-Meteo weather client: local building weather and national market weather.

Endpoints (all free, no key, non-commercial use):

* forecast:            https://api.open-meteo.com/v1/forecast
* historical forecast: https://historical-forecast-api.open-meteo.com/v1/forecast
* previous runs:       https://previous-runs-api.open-meteo.com/v1/forecast
* archive (ERA5):      https://archive-api.open-meteo.com/v1/archive

Multiple coordinates can be requested in one call (comma separated); the
response is then a list with one item per location.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
import logging
import math
from statistics import fmean, pstdev
from typing import Any

import aiohttp

from .base import ProviderDataError, request_json

_LOGGER = logging.getLogger(__name__)

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
HISTORICAL_FORECAST_URL = "https://historical-forecast-api.open-meteo.com/v1/forecast"
PREVIOUS_RUNS_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"

LOCAL_VARS = [
    "temperature_2m",
    "relative_humidity_2m",
    "cloud_cover",
    "precipitation",
    "wind_speed_10m",
    "wind_speed_80m",
    "wind_speed_120m",
    "shortwave_radiation",
    "direct_radiation",
    "weather_code",
]
NATIONAL_VARS = ["temperature_2m", "wind_speed_100m", "shortwave_radiation", "cloud_cover"]
DISAGREEMENT_MODELS = ["ecmwf_ifs025", "icon_seamless", "gfs_seamless"]


@dataclass(frozen=True, slots=True)
class Region:
    name: str
    lat: float
    lon: float
    wind_w: float  # share of installed wind capacity (approximate)
    solar_w: float  # share of installed PV capacity (approximate)
    demand_w: float  # share of electricity demand / population (approximate)


# Representative regions of Poland. Weights are coarse, documented in
# docs/FORECASTING.md, and only used to build relative indices.
REGIONS: tuple[Region, ...] = (
    Region("pomorze", 54.35, 17.70, 0.22, 0.05, 0.08),
    Region("zachodniopomorskie", 53.60, 15.30, 0.20, 0.06, 0.05),
    Region("warmia_mazury", 54.00, 20.70, 0.10, 0.04, 0.04),
    Region("kujawy_wielkopolska", 52.60, 17.80, 0.22, 0.14, 0.15),
    Region("lodzkie", 51.70, 19.40, 0.10, 0.10, 0.08),
    Region("mazowsze", 52.25, 21.00, 0.06, 0.16, 0.22),
    Region("slask_malopolska", 50.20, 19.30, 0.04, 0.20, 0.25),
    Region("lubelskie_podkarpacie", 50.90, 22.40, 0.04, 0.17, 0.10),
    Region("dolny_slask", 51.10, 16.90, 0.02, 0.08, 0.03),
)


def wind_power_index(speed_ms: float | None) -> float | None:
    """Normalised generic turbine power curve (hub height ~100 m)."""
    if speed_ms is None:
        return None
    if speed_ms < 3.0 or speed_ms >= 25.0:
        return 0.0
    if speed_ms >= 12.0:
        return 1.0
    return ((speed_ms - 3.0) / 9.0) ** 3


@dataclass(slots=True)
class WeatherHour:
    start: datetime
    values: dict[str, float | None] = field(default_factory=dict)

    def get(self, key: str) -> float | None:
        return self.values.get(key)

    def to_dict(self) -> dict[str, Any]:
        return {"start": self.start.isoformat(), **self.values}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WeatherHour:
        values = {k: v for k, v in data.items() if k != "start"}
        return cls(datetime.fromisoformat(data["start"]), values)


def _times(hourly: dict[str, Any]) -> list[datetime]:
    out = []
    for t in hourly.get("time", []):
        out.append(datetime.fromisoformat(t).replace(tzinfo=UTC))
    return out


def parse_local(payload: dict[str, Any] | list[dict[str, Any]]) -> list[WeatherHour]:
    item = payload[0] if isinstance(payload, list) else payload
    hourly = item.get("hourly")
    if not isinstance(hourly, dict):
        raise ProviderDataError("open-meteo: missing hourly block")
    times = _times(hourly)
    keys = [k for k in hourly if k != "time"]
    return [
        WeatherHour(t, {k: hourly[k][i] if i < len(hourly[k]) else None for k in keys}) for i, t in enumerate(times)
    ]


def build_national(
    payload: list[dict[str, Any]] | dict[str, Any],
    regions: tuple[Region, ...] = REGIONS,
    models: list[str] | None = None,
) -> list[WeatherHour]:
    """Aggregate per-region responses into national market weather features.

    With several ``models`` the variables are suffixed (``wind_speed_100m_icon_seamless``)
    and a model disagreement index is produced.
    """
    items = payload if isinstance(payload, list) else [payload]
    if len(items) != len(regions):
        raise ProviderDataError("open-meteo: region count mismatch")
    models = models or []
    times = _times(items[0]["hourly"])
    out: list[WeatherHour] = []
    for i, t in enumerate(times):
        temp = wind = solar = cloud = 0.0
        tw = ww = sw = 0.0
        spreads: list[float] = []
        for region, item in zip(regions, items, strict=True):
            hourly = item["hourly"]

            def val(var: str, _hourly: dict[str, Any] = hourly, i: int = i) -> float | None:
                if models:
                    vals = [
                        _hourly.get(f"{var}_{m}", [None] * (i + 1))[i]
                        for m in models
                        if i < len(_hourly.get(f"{var}_{m}", []))
                    ]
                    vals = [v for v in vals if v is not None]
                    return fmean(vals) if vals else None
                series = _hourly.get(var) or []
                return series[i] if i < len(series) else None

            t2m = val("temperature_2m")
            w100 = val("wind_speed_100m")
            rad = val("shortwave_radiation")
            cc = val("cloud_cover")
            if t2m is not None:
                temp += region.demand_w * t2m
                tw += region.demand_w
            if w100 is not None:
                wind += region.wind_w * (wind_power_index(w100) or 0.0)
                ww += region.wind_w
            if rad is not None:
                solar += region.solar_w * rad
                cloud += region.solar_w * (cc or 0.0)
                sw += region.solar_w
            if models:
                members = [
                    wind_power_index(hourly.get(f"wind_speed_100m_{m}", [None] * (i + 1))[i])
                    for m in models
                    if i < len(hourly.get(f"wind_speed_100m_{m}", []))
                ]
                members = [m for m in members if m is not None]
                if len(members) >= 2:
                    spreads.append(region.wind_w * pstdev(members))
        if tw == 0 and ww == 0 and sw == 0:
            continue
        t_mean = temp / tw if tw else None
        values: dict[str, float | None] = {
            "national_temperature": t_mean,
            "national_hdd": None if t_mean is None else max(0.0, 18.0 - t_mean),
            "national_cdd": None if t_mean is None else max(0.0, t_mean - 22.0),
            "national_wind_index": wind / ww if ww else None,
            "national_solar_index": solar / sw if sw else None,
            "national_cloud_cover": cloud / sw if sw else None,
        }
        if spreads:
            values["wind_model_spread"] = sum(spreads) / max(ww, 1e-9)
        out.append(WeatherHour(t, values))
    return out


class WeatherClient:
    def __init__(self, session: aiohttp.ClientSession, model: str = "ecmwf_ifs025") -> None:
        self._session = session
        self.model = model
        self.last_error: str | None = None

    async def local_forecast(self, lat: float, lon: float, days: int = 7) -> list[WeatherHour]:
        params = {
            "latitude": round(lat, 3),
            "longitude": round(lon, 3),
            "hourly": ",".join(LOCAL_VARS),
            "forecast_days": min(16, max(1, days + 1)),
            "past_days": 1,
            "timezone": "GMT",
            "wind_speed_unit": "ms",
        }
        if self.model != "best_match":
            params["models"] = self.model
        data = await request_json(self._session, "GET", FORECAST_URL, params=params, provider="open-meteo")
        self.last_error = None
        return parse_local(data)

    async def national_forecast(self, days: int = 7, with_spread: bool = True) -> list[WeatherHour]:
        models = DISAGREEMENT_MODELS if with_spread else ([] if self.model == "best_match" else [self.model])
        params: dict[str, Any] = {
            "latitude": ",".join(str(r.lat) for r in REGIONS),
            "longitude": ",".join(str(r.lon) for r in REGIONS),
            "hourly": ",".join(NATIONAL_VARS),
            "forecast_days": min(16, max(1, days + 1)),
            "past_days": 1,
            "timezone": "GMT",
            "wind_speed_unit": "ms",
        }
        if models:
            params["models"] = ",".join(models)
        data = await request_json(self._session, "GET", FORECAST_URL, params=params, provider="open-meteo")
        self.last_error = None
        return build_national(data, models=models if len(models) > 1 else None)

    async def national_historical(self, start: date, end: date) -> list[WeatherHour]:
        """Archived short-lead forecasts for training (not observations)."""
        params: dict[str, Any] = {
            "latitude": ",".join(str(r.lat) for r in REGIONS),
            "longitude": ",".join(str(r.lon) for r in REGIONS),
            "hourly": ",".join(NATIONAL_VARS),
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "timezone": "GMT",
            "wind_speed_unit": "ms",
        }
        if self.model != "best_match":
            params["models"] = self.model
        data = await request_json(
            self._session, "GET", HISTORICAL_FORECAST_URL, params=params, timeout=120, provider="open-meteo"
        )
        return build_national(data)

    async def local_historical(self, lat: float, lon: float, start: date, end: date) -> list[WeatherHour]:
        params = {
            "latitude": round(lat, 3),
            "longitude": round(lon, 3),
            "hourly": "temperature_2m,shortwave_radiation,wind_speed_10m",
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "timezone": "GMT",
            "wind_speed_unit": "ms",
        }
        data = await request_json(self._session, "GET", ARCHIVE_URL, params=params, timeout=120, provider="open-meteo")
        return parse_local(data)


def is_finite(value: float | None) -> bool:
    return value is not None and not math.isnan(value) and not math.isinf(value)
