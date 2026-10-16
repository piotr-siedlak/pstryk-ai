"""PSE (Polskie Sieci Elektroenergetyczne) API v2 client.

Base URL: https://api.raporty.pse.pl/api/ (OData-like, ``$filter`` on
``business_date``, paging through ``nextLink``). No authentication.

Verified datasets (October 2026):

* ``pk5l-wp``    – coordinated multi-day plan (≈6 days ahead), hourly:
                   ``grid_demand_fcst``, ``fcst_wi_tot_gen``, ``fcst_pv_tot_gen``,
                   ``planned_exchange``; ``plan_dtime_utc`` marks the END of the hour.
* ``kse-load``   – load forecast/actual, 15 min (``load_fcst``, ``load_actual``).
* ``his-wlk-cal``– realised generation, 15 min (``demand``, ``wi``, ``pv``).
* ``rce-pln``    – RCE balancing-related price, 15 min. **RCE is not the TGE RDN
                   day-ahead price** and is kept as a separate dataset.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import logging
from typing import Any

import aiohttp

from ..models.price_slot import MarketPoint
from .base import ProviderDataError, request_json

_LOGGER = logging.getLogger(__name__)

PSE_URL = "https://api.raporty.pse.pl/api/"
MAX_PAGES = 200


def parse_pse_time(text: str) -> datetime:
    """PSE ``*_utc`` fields look like ``2026-10-14 22:15:00`` (UTC)."""
    text = text.strip().replace("T", " ")
    if "." in text:
        text = text.split(".", 1)[0]
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    except ValueError as err:
        raise ProviderDataError(f"pse: bad time {text!r}") from err


@dataclass(slots=True)
class SystemForecastHour:
    """Hourly power-system indicators (MW)."""

    start: datetime
    demand_mw: float | None
    wind_mw: float | None
    pv_mw: float | None
    exchange_mw: float | None
    published_at: datetime | None

    @property
    def residual_mw(self) -> float | None:
        if self.demand_mw is None:
            return None
        return self.demand_mw - (self.wind_mw or 0.0) - (self.pv_mw or 0.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": self.start.isoformat(),
            "demand_mw": self.demand_mw,
            "wind_mw": self.wind_mw,
            "pv_mw": self.pv_mw,
            "exchange_mw": self.exchange_mw,
            "published_at": self.published_at.isoformat() if self.published_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SystemForecastHour:
        return cls(
            start=datetime.fromisoformat(data["start"]),
            demand_mw=data.get("demand_mw"),
            wind_mw=data.get("wind_mw"),
            pv_mw=data.get("pv_mw"),
            exchange_mw=data.get("exchange_mw"),
            published_at=datetime.fromisoformat(data["published_at"]) if data.get("published_at") else None,
        )


def _f(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


def parse_pk5l(rows: list[dict[str, Any]]) -> list[SystemForecastHour]:
    out: dict[datetime, SystemForecastHour] = {}
    for row in rows:
        try:
            end = parse_pse_time(row["plan_dtime_utc"])
        except (KeyError, ProviderDataError):
            continue
        pub = row.get("publication_ts_utc")
        item = SystemForecastHour(
            start=end - timedelta(hours=1),
            demand_mw=_f(row.get("grid_demand_fcst")),
            wind_mw=_f(row.get("fcst_wi_tot_gen")),
            pv_mw=_f(row.get("fcst_pv_tot_gen")),
            exchange_mw=_f(row.get("planned_exchange")),
            published_at=parse_pse_time(pub) if pub else None,
        )
        prev = out.get(item.start)
        if prev is None or (item.published_at or datetime.min.replace(tzinfo=UTC)) >= (
            prev.published_at or datetime.min.replace(tzinfo=UTC)
        ):
            out[item.start] = item
    return [out[k] for k in sorted(out)]


def parse_his_wlk_cal(rows: list[dict[str, Any]]) -> list[SystemForecastHour]:
    """Aggregate realised 15-min generation to hourly means (complete hours only)."""
    buckets: dict[datetime, list[dict[str, Any]]] = {}
    for row in rows:
        try:
            end = parse_pse_time(row["dtime_utc"])
        except (KeyError, ProviderDataError):
            continue
        start = end - timedelta(minutes=15)
        buckets.setdefault(start.replace(minute=0), []).append(row)
    out = []
    for hour, items in sorted(buckets.items()):
        if len(items) != 4:
            continue

        def mean(key: str, items: list[dict[str, Any]] = items) -> float | None:
            vals = [_f(i.get(key)) for i in items]
            vals = [v for v in vals if v is not None]
            return sum(vals) / len(vals) if vals else None

        out.append(
            SystemForecastHour(
                start=hour,
                demand_mw=mean("demand"),
                wind_mw=mean("wi"),
                pv_mw=mean("pv"),
                exchange_mw=None,
                published_at=None,
            )
        )
    return out


def parse_rce(rows: list[dict[str, Any]]) -> list[MarketPoint]:
    out = []
    for row in rows:
        try:
            end = parse_pse_time(row["dtime_utc"])
            price = float(row["rce_pln"])
        except (KeyError, TypeError, ValueError, ProviderDataError):
            continue
        pub = row.get("publication_ts_utc")
        out.append(
            MarketPoint(
                start=end - timedelta(minutes=15),
                end=end,
                price_pln_mwh=price,
                provider="pse_rce",
                product="quarter_hour",
                published_at=parse_pse_time(pub) if pub else None,
            )
        )
    return sorted(out, key=lambda p: p.start)


class PseClient:
    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session
        self.last_error: str | None = None

    async def fetch(self, entity: str, first_day: date, last_day: date) -> list[dict[str, Any]]:
        params = {
            "$filter": f"business_date ge '{first_day.isoformat()}' and business_date le '{last_day.isoformat()}'",
        }
        url: str | None = PSE_URL + entity
        rows: list[dict[str, Any]] = []
        pages = 0
        while url and pages < MAX_PAGES:
            data = await request_json(self._session, "GET", url, params=params, timeout=60, provider="pse")
            if not isinstance(data, dict) or not isinstance(data.get("value"), list):
                raise ProviderDataError(f"pse: unexpected payload for {entity}")
            rows.extend(data["value"])
            url = data.get("nextLink")
            params = None  # nextLink already contains the query
            pages += 1
        self.last_error = None
        return rows

    async def system_forecast(self, first_day: date, last_day: date) -> list[SystemForecastHour]:
        return parse_pk5l(await self.fetch("pk5l-wp", first_day, last_day))

    async def realised_generation(self, first_day: date, last_day: date) -> list[SystemForecastHour]:
        return parse_his_wlk_cal(await self.fetch("his-wlk-cal", first_day, last_day))

    async def rce_prices(self, first_day: date, last_day: date) -> list[MarketPoint]:
        return parse_rce(await self.fetch("rce-pln", first_day, last_day))
