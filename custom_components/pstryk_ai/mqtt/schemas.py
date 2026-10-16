"""Versioned MQTT payload builders (pure Python).

Every JSON payload is an envelope::

    {"schema": "pstryk_ai/v1", "type": "...", "generated_at": ISO, "valid_until": ISO,
     "unit": "PLN/kWh", "data": ...}

Time-series records carry ``start, end, value, unit, source, quality,
generated_at, valid_until`` (+ ``p10/p50/p90/confidence`` for forecasts).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
from typing import Any
from zoneinfo import ZoneInfo

from ..const import LOCAL_TZ
from ..models.price_slot import PriceSlot, iso

SCHEMA = "pstryk_ai/v1"
TZ = ZoneInfo(LOCAL_TZ)


@dataclass(slots=True)
class Message:
    topic: str  # relative to the prefix
    payload: str
    retain: bool = True
    expiry_s: int | None = None  # MQTT v5 message expiry


def envelope(
    kind: str, data: Any, generated_at: datetime, valid_until: datetime | None, unit: str | None = None
) -> str:
    body: dict[str, Any] = {
        "schema": SCHEMA,
        "type": kind,
        "generated_at": iso(generated_at),
        "valid_until": iso(valid_until),
        "data": data,
    }
    if unit:
        body["unit"] = unit
    return json.dumps(body, separators=(",", ":"), ensure_ascii=False)


def scalar(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return f"{value:.5f}".rstrip("0").rstrip(".") if abs(value) < 1e6 else str(value)
    if isinstance(value, datetime):
        return iso(value) or ""
    return str(value)


def records(slots: list[PriceSlot]) -> list[dict[str, Any]]:
    return [s.as_record() for s in slots]


def local_day_slots(slots: list[PriceSlot], day_offset: int, now: datetime) -> list[PriceSlot]:
    target = (now.astimezone(TZ) + timedelta(days=day_offset)).date()
    return [s for s in slots if s.start.astimezone(TZ).date() == target]


def evcc_payload(slots: list[PriceSlot]) -> str:
    """EVCC 'forecast' tariff format: list of {start, end, value} (currency/kWh)."""
    return json.dumps(
        [{"start": iso(s.start), "end": iso(s.end), "value": round(s.value, 5)} for s in slots if s.value is not None],
        separators=(",", ":"),
    )


def compact_series(slots: list[PriceSlot]) -> dict[str, Any]:
    """Columnar encoding for the 168 h topic (keeps message size small)."""
    return {
        "start": [iso(s.start) for s in slots],
        "value": [None if s.value is None else round(s.value, 5) for s in slots],
        "p10": [None if s.p10 is None else round(s.p10, 5) for s in slots],
        "p90": [None if s.p90 is None else round(s.p90, 5) for s in slots],
        "source": [s.source.value for s in slots],
        "confidence": [None if s.confidence is None else round(s.confidence, 3) for s in slots],
        "resolution": "PT60M",
    }
