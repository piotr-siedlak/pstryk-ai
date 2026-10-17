"""Domestic hot water (CWU) helpers: draw profile, ready times, legionella."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from ..const import LOCAL_TZ
from .thermal_storage import ReadyConstraint

TZ = ZoneInfo(LOCAL_TZ)

# Typical share of daily hot-water use per local hour (sums to 1.0).
DEFAULT_PROFILE: tuple[float, ...] = (
    0.0,
    0.0,
    0.0,
    0.0,
    0.0,
    0.01,
    0.08,
    0.12,
    0.07,
    0.04,
    0.03,
    0.03,
    0.04,
    0.03,
    0.02,
    0.02,
    0.03,
    0.05,
    0.08,
    0.12,
    0.11,
    0.07,
    0.04,
    0.01,
)


def parse_times(text: str | None) -> list[tuple[int, int]]:
    """Parse ``"06:00, 19:30"`` into [(6, 0), (19, 30)]."""
    out = []
    for part in str(text or "").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        hh, _, mm = part.partition(":")
        try:
            h, m = int(hh), int(mm or 0)
        except ValueError:
            continue
        if 0 <= h <= 23 and 0 <= m <= 59:
            out.append((h, m))
    return sorted(set(out))


def daily_draw_kwh(liters_per_day: float, cold_t: float = 10.0, use_t: float = 45.0) -> float:
    """Heat needed for the daily hot-water volume (mixed to ``use_t``)."""
    return max(0.0, liters_per_day) * 0.001163 * max(0.0, use_t - cold_t)


def draw_series(
    hours: Sequence[datetime],
    liters_per_day: float,
    profile: Sequence[float] | None = None,
    cold_t: float = 10.0,
    use_t: float = 45.0,
) -> list[float]:
    """Thermal draw (kW) per hourly slot start (UTC) using an hour-of-day profile."""
    prof = list(profile) if profile and len(profile) == 24 and sum(profile) > 0 else list(DEFAULT_PROFILE)
    total = sum(prof)
    prof = [p / total for p in prof]
    daily = daily_draw_kwh(liters_per_day, cold_t, use_t)
    return [daily * prof[h.astimezone(TZ).hour] for h in hours]


def ready_constraints(
    now: datetime, times: list[tuple[int, int]], min_t: float, horizon_h: int = 72
) -> list[ReadyConstraint]:
    out: list[ReadyConstraint] = []
    local_now = now.astimezone(TZ)
    for day_offset in range(0, horizon_h // 24 + 2):
        d: date = (local_now + timedelta(days=day_offset)).date()
        for h, m in times:
            at = datetime(d.year, d.month, d.day, h, m, tzinfo=TZ)
            if now < at <= now + timedelta(hours=horizon_h):
                out.append(ReadyConstraint(at=at, min_t=min_t))
    return out


def legionella_due(last_done: datetime | None, now: datetime, interval_days: int = 7) -> tuple[bool, int]:
    """(due?, hours until deadline). Due when the last cycle is older than the interval minus one day."""
    if last_done is None:
        return True, 24
    deadline = last_done + timedelta(days=interval_days)
    hours_left = int((deadline - now).total_seconds() // 3600)
    return hours_left <= 24, max(1, min(48, hours_left if hours_left > 0 else 24))
