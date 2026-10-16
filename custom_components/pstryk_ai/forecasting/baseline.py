"""Model A — deterministic seasonal baseline.

prediction(target) = similar-day hourly profile + damped recent level shift

* profile: mean price at the same local hour on days of the same type
  (working day / Saturday / Sunday+holiday) within the last 4 weeks of known
  data, falling back to all days when fewer than two matches exist;
* level shift: (mean of last 3 known days − mean of last 28 known days),
  damped by 0.8^k so that far horizons revert to the profile.

The baseline needs only market price history, so a forecast is always
available even when no ML model can be trained or loaded.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime, timedelta
from statistics import fmean

from .features import day_start_utc, day_type, horizon_day, local_date, local_hour

MODEL_NAME = "seasonal_baseline"
MODEL_VERSION = "1"


class BaselineModel:
    name = MODEL_NAME
    version = MODEL_VERSION

    def __init__(self, lookback_days: int = 28, damping: float = 0.8) -> None:
        self.lookback_days = lookback_days
        self.damping = damping

    def _day_hours(self, prices: Mapping[datetime, float], day: date) -> list[tuple[datetime, float]]:
        start = day_start_utc(day)
        end = day_start_utc(day + timedelta(days=1))
        out = []
        cursor = start
        while cursor < end:
            value = prices.get(cursor)
            if value is not None:
                out.append((cursor, value))
            cursor += timedelta(hours=1)
        return out

    def predict(self, target: datetime, last_known_day: date, prices: Mapping[datetime, float]) -> float | None:
        k = max(1, horizon_day(target, last_known_day))
        hour = local_hour(target)
        dtype = day_type(local_date(target))
        same_type: list[float] = []
        any_type: list[float] = []
        recent: list[float] = []
        long: list[float] = []
        for back in range(self.lookback_days):
            day = last_known_day - timedelta(days=back)
            hours = self._day_hours(prices, day)
            if not hours:
                continue
            values = [v for _, v in hours]
            long.extend(values)
            if back < 3:
                recent.extend(values)
            at_hour = [v for h, v in hours if local_hour(h) == hour]
            if not at_hour:
                continue
            any_type.append(at_hour[0])
            if day_type(day) == dtype:
                same_type.append(at_hour[0])
        pool = same_type if len(same_type) >= 2 else any_type
        if not pool:
            return None
        # weight recent weeks more (linear decay)
        weights = [1.0 / (1 + i * 0.15) for i in range(len(pool))]
        profile = sum(w * v for w, v in zip(weights, pool, strict=True)) / sum(weights)
        shift = 0.0
        if recent and long:
            shift = (fmean(recent) - fmean(long)) * (self.damping**k)
        return profile + shift
