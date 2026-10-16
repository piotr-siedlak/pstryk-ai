"""ENTSO-E Transparency Platform client (day-ahead prices, bidding zone PL).

Requires a free security token (https://transparency.entsoe.eu/ → My Account
Settings → Web API Security Token). Document type A44 (price document).
Supports PT15M and PT60M resolutions and curve type A03 (positions omitted
when the value repeats).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
import re
import xml.etree.ElementTree as ET

import aiohttp

from ..models.price_slot import MarketPoint
from .base import ProviderAuthError, ProviderDataError, request_json

_LOGGER = logging.getLogger(__name__)

ENTSOE_URL = "https://web-api.tp.entsoe.eu/api"
PL_AREA = "10YPL-AREA-----S"
MAX_CHUNK = timedelta(days=90)

_RES = {"PT15M": 15, "PT30M": 30, "PT60M": 60, "PT1H": 60}


def _strip_ns(root: ET.Element) -> ET.Element:
    for elem in root.iter():
        if "}" in elem.tag:
            elem.tag = elem.tag.split("}", 1)[1]
    return root


def _fmt(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y%m%d%H%M")


def _parse_ts(text: str) -> datetime:
    text = text.strip()
    for fmt in ("%Y-%m-%dT%H:%MZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=UTC)
        except ValueError:
            continue
    raise ProviderDataError(f"entsoe: bad timestamp {text!r}")


def parse_price_document(xml_text: str, eur_pln: float) -> list[MarketPoint]:
    """Parse an A44 document into market points in PLN/MWh."""
    try:
        root = _strip_ns(ET.fromstring(xml_text))
    except ET.ParseError as err:
        raise ProviderDataError("entsoe: invalid XML") from err

    if root.tag == "Acknowledgement_MarketDocument":
        reason = root.findtext(".//Reason/text") or "no data"
        if "No matching data" in reason:
            return []
        if "authorized" in reason.lower() or "token" in reason.lower():
            raise ProviderAuthError(f"entsoe: {reason}")
        raise ProviderDataError(f"entsoe: {reason}")

    points: dict[tuple[datetime, int], MarketPoint] = {}
    created = root.findtext("createdDateTime")
    published = _parse_ts(created.replace(".000", "")) if created and re.match(r"\d{4}-", created) else None
    for series in root.findall(".//TimeSeries"):
        currency = (series.findtext("currency_Unit.name") or "EUR").upper()
        factor = 1.0 if currency == "PLN" else eur_pln
        for period in series.findall("Period"):
            resolution = period.findtext("resolution") or "PT60M"
            minutes = _RES.get(resolution)
            if minutes is None:
                continue
            start = _parse_ts(period.findtext("timeInterval/start") or "")
            end = _parse_ts(period.findtext("timeInterval/end") or "")
            raw = sorted(
                (int(p.findtext("position") or 0), float(p.findtext("price.amount") or "nan"))
                for p in period.findall("Point")
            )
            if not raw:
                continue
            total = int((end - start).total_seconds() // (minutes * 60))
            by_pos = dict(raw)
            last: float | None = None
            for pos in range(1, total + 1):
                if pos in by_pos:
                    last = by_pos[pos]
                if last is None:
                    continue
                slot_start = start + timedelta(minutes=(pos - 1) * minutes)
                key = (slot_start, minutes)
                points[key] = MarketPoint(
                    start=slot_start,
                    end=slot_start + timedelta(minutes=minutes),
                    price_pln_mwh=last * factor,
                    provider="entsoe",
                    product="hourly" if minutes == 60 else "quarter_hour",
                    published_at=published,
                )
    return [points[k] for k in sorted(points)]


class EntsoeClient:
    def __init__(self, session: aiohttp.ClientSession, token: str, eur_pln: float) -> None:
        self._session = session
        self._token = token
        self._eur_pln = eur_pln
        self.last_error: str | None = None

    async def fetch_day_ahead(self, start: datetime, end: datetime) -> list[MarketPoint]:
        out: list[MarketPoint] = []
        cursor = start
        while cursor < end:
            chunk_end = min(end, cursor + MAX_CHUNK)
            try:
                text = await request_json(
                    self._session,
                    "GET",
                    ENTSOE_URL,
                    params={
                        "securityToken": self._token,
                        "documentType": "A44",
                        "in_Domain": PL_AREA,
                        "out_Domain": PL_AREA,
                        "periodStart": _fmt(cursor),
                        "periodEnd": _fmt(chunk_end),
                    },
                    headers={"Accept": "application/xml"},
                    expect="text",
                    timeout=60,
                    provider="entsoe",
                )
            except ProviderDataError as err:
                if "No matching data" not in str(err):
                    self.last_error = str(err)[:80]
                    raise
                text = ""
            if text:
                out.extend(parse_price_document(text, self._eur_pln))
            cursor = chunk_end
        self.last_error = None
        return out
