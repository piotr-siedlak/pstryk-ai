"""TGE (Towarowa Giełda Energii) RDN client — OPT-IN, experimental.

TGE does not offer a public API for RDN results; the public results page
(https://tge.pl/energia-elektryczna-rdn) is HTML. This client fetches at most
a couple of pages per day (after Fixing I ≈10:30 and Fixing II ≈13:50) for
private use, parses only the published table and never redistributes it.
Check TGE's terms before enabling. ENTSO-E is the recommended source.

Table layout (since the 2025/2026 15-minute market change) — each row:

``label | duration_min | FI price PLN/MWh | FI volume | continuous price |
continuous volume | FII price EUR/MWh | FII price PLN/MWh | FII volume | ...``

Labels: ``YYYY-MM-DD_Hnn`` (hourly product, H01 = 00:00–01:00, DST hour
``H02a``) and ``YYYY-MM-DD_Qhh:mm`` (quarter-hour product; label is the END
of the quarter). Since 2026-06-10 hourly Fixing I prices are derived from
15-minute products — we keep both resolutions separately.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from html.parser import HTMLParser
import logging
import re
from zoneinfo import ZoneInfo

import aiohttp

from ..const import LOCAL_TZ
from ..models.price_slot import MarketPoint
from .base import request_json

_LOGGER = logging.getLogger(__name__)

TGE_URL = "https://tge.pl/energia-elektryczna-rdn"
TZ = ZoneInfo(LOCAL_TZ)

_H = re.compile(r"^(\d{4}-\d{2}-\d{2})_H(\d{2})([a-z]?)$")
_Q = re.compile(r"^(\d{4}-\d{2}-\d{2})_Q(\d{2}):(\d{2})([a-z]?)$")

COL_FIXING_I = 2
COL_FIXING_II_PLN = 7


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.rows: list[list[str]] = []
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        if tag == "tr":
            self._row = []
        elif tag in ("td", "th") and self._row is not None:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("td", "th") and self._row is not None and self._cell is not None:
            self._row.append(" ".join("".join(self._cell).split()))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def _num(text: str) -> float | None:
    text = text.replace("\xa0", "").replace(" ", "").replace(",", ".")
    if text in ("", "-", "—"):
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _local_to_utc(day: date, minutes_from_midnight: int, dst_second: bool) -> datetime:
    """Convert a local wall-clock offset to UTC, handling the repeated DST hour."""
    base = datetime(day.year, day.month, day.day, tzinfo=TZ)
    local = base + timedelta(minutes=minutes_from_midnight)
    naive = local.replace(tzinfo=None)
    aware = naive.replace(tzinfo=TZ, fold=1 if dst_second else 0)
    return aware.astimezone(UTC)


def parse_rdn_html(html: str, *, fixing: str = "I") -> list[MarketPoint]:
    """Parse the TGE RDN results table into market points (PLN/MWh)."""
    parser = _TableParser()
    parser.feed(html)
    col = COL_FIXING_I if fixing == "I" else COL_FIXING_II_PLN
    points: list[MarketPoint] = []
    for row in parser.rows:
        if not row:
            continue
        label = row[0]
        if (m := _H.match(label)) is not None:
            day = date.fromisoformat(m.group(1))
            hour = int(m.group(2))
            dst_second = m.group(3) == "a"
            if len(row) <= col:
                continue
            price = _num(row[col])
            if price is None:
                continue
            start = _local_to_utc(day, (hour - 1) * 60, dst_second)
            # On the DST-end day H02 and H02a are both 02:00 local; H03+ shift.
            points.append(MarketPoint(start, start + timedelta(hours=1), price, f"tge_fixing_{fixing}", "hourly"))
        elif (m := _Q.match(label)) is not None:
            day = date.fromisoformat(m.group(1))
            end_minutes = int(m.group(2)) * 60 + int(m.group(3))
            dst_second = m.group(4) == "a"
            if len(row) <= col:
                continue
            price = _num(row[col])
            if price is None:
                continue
            start = _local_to_utc(day, end_minutes - 15, dst_second)
            points.append(
                MarketPoint(start, start + timedelta(minutes=15), price, f"tge_fixing_{fixing}", "quarter_hour")
            )
    return _dedupe_by_utc(points)


def _dedupe_by_utc(points: list[MarketPoint]) -> list[MarketPoint]:
    """Wall-clock labels are ambiguous around DST; rebuild a strictly increasing UTC series.

    Rows appear in delivery order, so for each product we place them
    sequentially from the first row's UTC start.
    """
    out: list[MarketPoint] = []
    for product, step in (("hourly", timedelta(hours=1)), ("quarter_hour", timedelta(minutes=15))):
        items = [p for p in points if p.product == product]
        if not items:
            continue
        cursor = items[0].start
        for item in items:
            out.append(MarketPoint(cursor, cursor + step, item.price_pln_mwh, item.provider, product))
            cursor += step
    return sorted(out, key=lambda p: (p.product, p.start))


class TgeClient:
    def __init__(self, session: aiohttp.ClientSession) -> None:
        self._session = session
        self.last_error: str | None = None

    async def fetch_delivery_day(self, delivery: date, fixing: str = "I") -> list[MarketPoint]:
        # The page shows contracts for the day AFTER ``dateShow``.
        show = delivery - timedelta(days=1)
        html = await request_json(
            self._session,
            "GET",
            TGE_URL,
            params={"dateShow": show.strftime("%d-%m-%Y")},
            headers={"Accept": "text/html"},
            expect="text",
            timeout=45,
            retries=1,
            provider="tge",
        )
        points = [p for p in parse_rdn_html(html, fixing=fixing) if p.start.astimezone(TZ).date() == delivery]
        self.last_error = None if points else "no_data"
        return points
