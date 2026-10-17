"""Feature engineering for hourly day-ahead price forecasting.

The central concept is the *horizon day* ``k``: the number of local calendar
days between the last fully known market day and the target day. ``k = 1``
means "tomorrow, before the auction results are known". Every feature for a
target hour is computed only from information available at the end of the
last known day, which prevents target leakage in training and backtests.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
import math
from statistics import fmean, pstdev
from zoneinfo import ZoneInfo

from ..const import LOCAL_TZ

TZ = ZoneInfo(LOCAL_TZ)
MAX_HORIZON_DAYS = 7


def easter(year: int) -> date:
    """Gregorian Easter Sunday (anonymous algorithm)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l_ = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l_) // 451
    month = (h + l_ - 7 * m + 114) // 31
    day = ((h + l_ - 7 * m + 114) % 31) + 1
    return date(year, month, day)


@lru_cache(maxsize=64)
def polish_holidays(year: int) -> frozenset[date]:
    """Statutory public holidays in Poland (Christmas Eve since 2025)."""
    e = easter(year)
    days = {
        date(year, 1, 1),
        date(year, 1, 6),
        e,
        e + timedelta(days=1),
        date(year, 5, 1),
        date(year, 5, 3),
        e + timedelta(days=49),  # Pentecost (Sunday)
        e + timedelta(days=60),  # Corpus Christi
        date(year, 8, 15),
        date(year, 11, 1),
        date(year, 11, 11),
        date(year, 12, 25),
        date(year, 12, 26),
    }
    if year >= 2025:
        days.add(date(year, 12, 24))
    return frozenset(days)


def is_holiday(day: date) -> bool:
    return day in polish_holidays(day.year)


def day_type(day: date) -> int:
    """0 = working day, 1 = Saturday, 2 = Sunday or public holiday."""
    if day.weekday() == 6 or is_holiday(day):
        return 2
    if day.weekday() == 5:
        return 1
    return 0


def local_date(moment: datetime) -> date:
    return moment.astimezone(TZ).date()


def local_hour(moment: datetime) -> int:
    return moment.astimezone(TZ).hour


def day_start_utc(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, tzinfo=TZ).astimezone(UTC)


def horizon_day(target: datetime, last_known_day: date) -> int:
    return (local_date(target) - last_known_day).days


@dataclass(slots=True)
class FeatureContext:
    """Inputs for feature construction (UTC hour-start keyed mappings)."""

    prices: Mapping[datetime, float]  # PLN/MWh, known values only
    system: Mapping[datetime, object]  # SystemForecastHour-like (demand_mw, wind_mw, ...)
    weather: Mapping[datetime, object]  # WeatherHour-like (.get(key))


FEATURE_NAMES: list[str] = (
    ["bias"]
    + [f"hour_{h}" for h in range(1, 24)]
    + ["saturday", "sunday_holiday", "month_sin", "month_cos"]
    + ["lag_same_hour", "mean7_same_hour", "last_day_mean", "last_day_std"]
    + ["demand_gw", "wind_gw", "pv_gw", "residual_gw", "exchange_gw", "pse_missing"]
    + ["temp", "hdd", "wind_index", "solar_index", "weather_missing"]
    + ["residual_x_peak", "pv_x_midday"]
)

# Typical values used when an input group is missing (keeps the vector usable;
# the *_missing flag lets the model learn the bias of that situation).
_FALLBACK_SYSTEM = (17.0, 3.0, 1.0, 13.0, 0.0)
_FALLBACK_WEATHER = (9.0, 9.0, 0.25, 120.0)


def _lag_price(prices: Mapping[datetime, float], target: datetime, days: int) -> float | None:
    return prices.get(target - timedelta(days=days))


def build_features(
    target: datetime,
    last_known_day: date,
    ctx: FeatureContext,
) -> list[float] | None:
    """Return the feature vector for ``target`` or ``None`` if lags are missing."""
    k = horizon_day(target, last_known_day)
    if k < 1:
        return None
    lag_days = k
    lag = _lag_price(ctx.prices, target, lag_days)
    if lag is None:
        # DST shifts can make the exact 24h multiple fall on a missing hour.
        lag = _lag_price(ctx.prices, target - timedelta(hours=1), lag_days)
    if lag is None:
        return None
    same_hour = [v for d in range(lag_days, lag_days + 7) if (v := _lag_price(ctx.prices, target, d)) is not None]
    start = day_start_utc(last_known_day)
    end = day_start_utc(last_known_day + timedelta(days=1))
    hours = int((end - start).total_seconds() // 3600)
    last_day = [v for i in range(hours) if (v := ctx.prices.get(start + timedelta(hours=i))) is not None]
    if len(last_day) < 20:
        return None

    lt = target.astimezone(TZ)
    hour = lt.hour
    dtype = day_type(lt.date())
    vec: list[float] = [1.0]
    vec += [1.0 if hour == h else 0.0 for h in range(1, 24)]
    vec += [1.0 if dtype == 1 else 0.0, 1.0 if dtype == 2 else 0.0]
    angle = 2 * math.pi * (lt.timetuple().tm_yday / 365.25)
    vec += [math.sin(angle), math.cos(angle)]
    vec += [lag, fmean(same_hour), fmean(last_day), pstdev(last_day)]

    sys_row = ctx.system.get(target)
    if sys_row is not None and getattr(sys_row, "demand_mw", None) is not None:
        demand = sys_row.demand_mw / 1000
        wind = (sys_row.wind_mw or 0.0) / 1000
        pv = (sys_row.pv_mw or 0.0) / 1000
        exch = (sys_row.exchange_mw or 0.0) / 1000
        vec += [demand, wind, pv, demand - wind - pv, exch, 0.0]
    else:
        vec += [*_FALLBACK_SYSTEM, 1.0]

    w = ctx.weather.get(target)
    temp = w.get("national_temperature") if w is not None else None
    if temp is not None:
        vec += [
            temp,
            w.get("national_hdd") or 0.0,
            w.get("national_wind_index") or 0.0,
            w.get("national_solar_index") or 0.0,
            0.0,
        ]
    else:
        vec += [*_FALLBACK_WEATHER, 1.0]

    residual = vec[FEATURE_NAMES.index("residual_gw")]
    pv_val = vec[FEATURE_NAMES.index("pv_gw")]
    peak = 1.0 if hour in (7, 8, 9, 17, 18, 19, 20) else 0.0
    midday = 1.0 if 10 <= hour <= 15 else 0.0
    vec += [residual * peak, pv_val * midday]
    return vec


def last_complete_day(prices: Mapping[datetime, float], until: datetime | None = None) -> date | None:
    """Most recent local day with ≥ 23 known hourly prices (≤ ``until``)."""
    counts: dict[date, int] = {}
    for hour in prices:
        if until is not None and hour >= until:
            continue
        d = local_date(hour)
        counts[d] = counts.get(d, 0) + 1
    complete = [d for d, c in counts.items() if c >= 23]
    return max(complete) if complete else None
