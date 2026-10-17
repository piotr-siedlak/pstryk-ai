"""Pstryk.pl integration API client.

Only the official, documented endpoint is used:
``GET /integrations/meter-data/unified-metrics/`` (see
https://api.pstryk.pl/integrations/schema/). Authentication is the raw API key
in the ``Authorization`` header.

Terms of use (https://pstryk.pl/regulamin-api) limit "heavy" endpoints to
3 requests/hour. Every request goes through a :class:`RequestBudget` that is
shared per API key, and HTTP 429 blocks the key for ``Retry-After`` seconds.
"""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime, timedelta
import hashlib
import logging
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp

from ..const import (
    LOCAL_TZ,
    PSTRYK_BASE_URL,
    PSTRYK_BUDGET_PER_HOUR,
    PSTRYK_BUDGET_WINDOW_S,
    PSTRYK_UNIFIED_PATH,
)
from ..models.energy_data import MeterFrame, PstrykSnapshot
from ..models.price_slot import PriceSlot, PriceSource, iso, parse_iso
from .base import (
    ProviderDataError,
    ProviderRateLimited,
    RequestBudget,
    request_json,
)

_LOGGER = logging.getLogger(__name__)

TZ = ZoneInfo(LOCAL_TZ)

# Pricing fields observed in the unified-metrics ``pricing`` metric.
BUY_KEYS = ("price_gross",)
BUY_NET_KEYS = ("price_net",)
SELL_KEYS = ("price_prosumer_gross",)
SELL_NET_KEYS = ("price_prosumer_net",)

_BUDGETS: dict[str, RequestBudget] = {}


def key_fingerprint(api_key: str) -> str:
    """Stable, non-reversible identifier of an API key (never log the key)."""
    return hashlib.sha256(api_key.encode()).hexdigest()[:12]


def shared_budget(api_key: str) -> RequestBudget:
    """Return the process-wide budget for this API key."""
    fp = key_fingerprint(api_key)
    if fp not in _BUDGETS:
        _BUDGETS[fp] = RequestBudget(PSTRYK_BUDGET_PER_HOUR, PSTRYK_BUDGET_WINDOW_S)
    return _BUDGETS[fp]


def _num(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(str(value).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None


def _metric(frame: dict[str, Any], *names: str) -> dict[str, Any]:
    metrics = frame.get("metrics") or {}
    for name in names:
        if isinstance(metrics.get(name), dict):
            return metrics[name]
    return {}


def _first(source: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        if key in source:
            value = _num(source.get(key))
            if value is not None:
                return value
    return None


def local_day_bounds(day: datetime) -> tuple[datetime, datetime]:
    """UTC bounds of the Europe/Warsaw calendar day containing ``day``."""
    local_date = day.astimezone(TZ).date()
    next_date = local_date + timedelta(days=1)
    start_local = datetime(local_date.year, local_date.month, local_date.day, tzinfo=TZ)
    end_local = datetime(next_date.year, next_date.month, next_date.day, tzinfo=TZ)
    return start_local.astimezone(UTC), end_local.astimezone(UTC)


def hours_in_local_day(day: datetime) -> int:
    start, end = local_day_bounds(day)
    return int((end - start).total_seconds() // 3600)


def is_placeholder_day(values: list[float | None], expected_hours: int) -> bool:
    """Detect unpublished placeholder prices.

    Before publication the API may return frames with missing or constant
    values. A day counts as confirmed only when every hour has a value and the
    prices are not (almost) all identical.
    """
    present = [v for v in values if v is not None]
    if len(present) < expected_hours:
        return True
    most_common = Counter(round(v, 5) for v in present).most_common(1)[0][1]
    return most_common / len(present) > 0.9


class PstrykClient:
    """Async client for the Pstryk integrations API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        api_key: str,
        *,
        budget: RequestBudget | None = None,
        base_url: str = PSTRYK_BASE_URL,
    ) -> None:
        self._session = session
        self._api_key = api_key
        self._base_url = base_url
        self.budget = budget or shared_budget(api_key)
        self.last_error: str | None = None
        self.last_success: datetime | None = None
        self.request_count = 0

    @property
    def fingerprint(self) -> str:
        return key_fingerprint(self._api_key)

    async def _get(self, params: dict[str, Any]) -> dict[str, Any]:
        if not self.budget.try_acquire():
            raise ProviderRateLimited(
                "pstryk: local request budget exhausted",
                self.budget.seconds_until_available(),
            )
        self.request_count += 1
        try:
            data = await request_json(
                self._session,
                "GET",
                self._base_url + PSTRYK_UNIFIED_PATH,
                params=params,
                headers={"Authorization": self._api_key},
                timeout=60,
                retries=0,  # a retry would consume another unit of the hourly limit
                provider="pstryk",
            )
        except ProviderRateLimited as err:
            self.budget.block_for(err.retry_after or PSTRYK_BUDGET_WINDOW_S)
            self.last_error = "rate_limited"
            raise
        except Exception as err:
            self.last_error = type(err).__name__
            raise
        if not isinstance(data, dict) or "frames" not in data:
            self.last_error = "invalid_payload"
            raise ProviderDataError("pstryk: response without frames")
        self.last_error = None
        return data

    async def fetch_hourly(self, window_start: datetime, window_end: datetime, metrics: list[str]) -> dict[str, Any]:
        """Fetch hourly frames (UTC; ``for_tz`` is not allowed with ``hour``)."""
        return await self._get(
            {
                "metrics": ",".join(metrics),
                "resolution": "hour",
                "window_start": _z(window_start),
                "window_end": _z(window_end),
            }
        )

    async def fetch_daily(self, window_start: datetime, window_end: datetime) -> dict[str, Any]:
        """Fetch daily frames aggregated for Europe/Warsaw."""
        return await self._get(
            {
                "metrics": "meter_values,cost",
                "resolution": "day",
                "for_tz": LOCAL_TZ,
                "window_start": _z(window_start),
                "window_end": _z(window_end),
            }
        )

    async def fetch_monthly(self, window_start: datetime, window_end: datetime) -> dict[str, Any]:
        """Fetch monthly totals (Europe/Warsaw months) – one small request for up to 12+ months."""
        return await self._get(
            {
                "metrics": "meter_values,cost",
                "resolution": "month",
                "for_tz": LOCAL_TZ,
                "window_start": _z(window_start),
                "window_end": _z(window_end),
            }
        )

    async def validate(self, now: datetime) -> dict[str, Any]:
        """Validate the key with a tiny pricing request (consumes one request)."""
        start = now.replace(minute=0, second=0, microsecond=0)
        return await self.fetch_hourly(start, start + timedelta(hours=1), ["pricing"])


def _z(value: datetime) -> str:
    return iso(value.replace(microsecond=0)) or ""


def parse_hourly(raw: dict[str, Any], now: datetime) -> PstrykSnapshot:
    """Parse an hourly unified-metrics response into a snapshot.

    Original values are preserved (PLN/kWh as returned by Pstryk). Prices of a
    local day are marked confirmed only if the day passes the placeholder check.
    """
    snapshot = PstrykSnapshot(fetched_at=now)
    frames = raw.get("frames") or []
    if not isinstance(frames, list):
        raise ProviderDataError("pstryk: frames is not a list")

    seen: set[datetime] = set()
    buy_by_day: dict[str, list[PriceSlot]] = {}
    sell_by_day: dict[str, list[PriceSlot]] = {}
    for frame in frames:
        try:
            start = parse_iso(frame["start"])
            end = parse_iso(frame["end"])
        except (KeyError, TypeError, ValueError):
            _LOGGER.debug("Skipping frame without valid start/end")
            continue
        if start in seen or end <= start:
            continue
        seen.add(start)
        pricing = _metric(frame, "pricing")
        meter = _metric(frame, "meterValues", "meter_values")
        cost = _metric(frame, "cost")
        day_key = start.astimezone(TZ).date().isoformat()

        for keys, net_keys, bucket, field_name in (
            (BUY_KEYS, BUY_NET_KEYS, buy_by_day, "buy"),
            (SELL_KEYS, SELL_NET_KEYS, sell_by_day, "sell"),
        ):
            value = _first(pricing, keys)
            if value is None:
                value = _first(frame, keys)
            if value is None:
                continue
            snapshot.price_fields[field_name] = True
            bucket.setdefault(day_key, []).append(
                PriceSlot(
                    start=start,
                    end=end,
                    value=value,
                    source=PriceSource.ACTUAL_PSTRYK,
                    is_cheap=pricing.get("is_cheap") if field_name == "buy" else None,
                    is_expensive=pricing.get("is_expensive") if field_name == "buy" else None,
                    generated_at=now,
                    meta={
                        "net": _first(pricing, net_keys),
                        "vat_included": True,
                        "pstryk_fields": sorted(pricing.keys()),
                    },
                )
            )

        if meter or cost:
            snapshot.hourly.append(
                MeterFrame(
                    start=start,
                    end=end,
                    import_kwh=_num(meter.get("energy_active_import_register")),
                    export_kwh=_num(meter.get("energy_active_export_register")),
                    balance_kwh=_num(meter.get("energy_balance")),
                    cost=dict(cost),
                    is_live=bool(frame.get("is_live")),
                )
            )

    today_key = now.astimezone(TZ).date().isoformat()
    tomorrow_key = (now.astimezone(TZ) + timedelta(days=1)).date().isoformat()
    for bucket, target in ((buy_by_day, snapshot.buy), (sell_by_day, snapshot.sell)):
        for day_key, slots in sorted(bucket.items()):
            expected = hours_in_local_day(slots[0].start)
            if is_placeholder_day([s.value for s in slots], expected):
                # Keep past/present hours of today (already billed), drop
                # speculative placeholders for future days.
                if day_key == today_key:
                    target.extend(s for s in slots if s.start <= now)
                continue
            target.extend(sorted(slots, key=lambda s: s.start))
            if bucket is buy_by_day and day_key == tomorrow_key:
                snapshot.tomorrow_confirmed = True

    snapshot.summary = raw.get("summary") or {}
    return snapshot


def parse_daily(raw: dict[str, Any]) -> tuple[list[MeterFrame], dict[str, Any]]:
    frames: list[MeterFrame] = []
    for frame in raw.get("frames") or []:
        try:
            start = parse_iso(frame["start"])
            end = parse_iso(frame["end"])
        except (KeyError, TypeError, ValueError):
            continue
        meter = _metric(frame, "meterValues", "meter_values")
        cost = _metric(frame, "cost")
        frames.append(
            MeterFrame(
                start=start,
                end=end,
                import_kwh=_num(meter.get("energy_active_import_register")),
                export_kwh=_num(meter.get("energy_active_export_register")),
                balance_kwh=_num(meter.get("energy_balance")),
                cost=dict(cost),
                is_live=bool(frame.get("is_live")),
            )
        )
    return frames, raw.get("summary") or {}
