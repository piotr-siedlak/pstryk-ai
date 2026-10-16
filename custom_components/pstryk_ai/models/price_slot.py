"""Price slot model shared by all modules.

All timestamps are timezone-aware UTC datetimes. Values are PLN/kWh unless the
``unit`` field says otherwise. A slot always carries its ``source`` so that a
forecast can never be mistaken for a confirmed Pstryk price.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any


class PriceSource(StrEnum):
    """Origin of a price value, ordered by precedence (highest first)."""

    ACTUAL_PSTRYK = "ACTUAL_PSTRYK"
    PUBLISHED_TGE = "PUBLISHED_TGE"
    MODEL_FORECAST = "MODEL_FORECAST"
    FALLBACK_FORECAST = "FALLBACK_FORECAST"
    UNAVAILABLE = "UNAVAILABLE"

    @property
    def is_confirmed(self) -> bool:
        return self is PriceSource.ACTUAL_PSTRYK

    @property
    def is_forecast(self) -> bool:
        return self in (PriceSource.MODEL_FORECAST, PriceSource.FALLBACK_FORECAST)

    @property
    def rank(self) -> int:
        return list(PriceSource).index(self)


QUALITY_CONFIRMED = "confirmed"
QUALITY_ESTIMATED = "estimated"
QUALITY_FORECAST = "forecast"
QUALITY_UNKNOWN = "unknown"

QUALITY_BY_SOURCE = {
    PriceSource.ACTUAL_PSTRYK: QUALITY_CONFIRMED,
    PriceSource.PUBLISHED_TGE: QUALITY_ESTIMATED,
    PriceSource.MODEL_FORECAST: QUALITY_FORECAST,
    PriceSource.FALLBACK_FORECAST: QUALITY_FORECAST,
    PriceSource.UNAVAILABLE: QUALITY_UNKNOWN,
}


def ensure_utc(value: datetime) -> datetime:
    """Return ``value`` as an aware UTC datetime (naive values are rejected)."""
    if value.tzinfo is None:
        raise ValueError(f"Naive datetime not allowed: {value!r}")
    return value.astimezone(UTC)


def floor_hour(value: datetime) -> datetime:
    value = ensure_utc(value)
    return value.replace(minute=0, second=0, microsecond=0)


def parse_iso(value: str) -> datetime:
    """Parse an ISO 8601 timestamp (``Z`` suffix allowed) into aware UTC."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return ensure_utc(value).isoformat().replace("+00:00", "Z")


@dataclass(slots=True)
class PriceSlot:
    """A single price interval."""

    start: datetime
    end: datetime
    value: float | None
    source: PriceSource
    unit: str = "PLN/kWh"
    p10: float | None = None
    p50: float | None = None
    p90: float | None = None
    confidence: float | None = None
    is_cheap: bool | None = None
    is_expensive: bool | None = None
    model_name: str | None = None
    generated_at: datetime | None = None
    valid_until: datetime | None = None
    meta: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.start = ensure_utc(self.start)
        self.end = ensure_utc(self.end)
        if self.end <= self.start:
            raise ValueError("Slot end must be after start")

    @property
    def duration(self) -> timedelta:
        return self.end - self.start

    @property
    def hours(self) -> float:
        return self.duration.total_seconds() / 3600

    @property
    def quality(self) -> str:
        return QUALITY_BY_SOURCE[self.source]

    def contains(self, moment: datetime) -> bool:
        return self.start <= ensure_utc(moment) < self.end

    def as_record(self) -> dict[str, Any]:
        """Versioned MQTT/attribute record (see docs/MQTT_TOPICS.md)."""
        record: dict[str, Any] = {
            "start": iso(self.start),
            "end": iso(self.end),
            "value": None if self.value is None else round(self.value, 5),
            "unit": self.unit,
            "source": self.source.value,
            "quality": self.quality,
            "generated_at": iso(self.generated_at),
            "valid_until": iso(self.valid_until),
        }
        if self.source.is_forecast or self.p10 is not None:
            record["p10"] = _r(self.p10)
            record["p50"] = _r(self.p50)
            record["p90"] = _r(self.p90)
            record["confidence"] = _r(self.confidence, 3)
        if self.is_cheap is not None:
            record["is_cheap"] = self.is_cheap
        if self.is_expensive is not None:
            record["is_expensive"] = self.is_expensive
        if self.model_name:
            record["model"] = self.model_name
        return record

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["start"] = iso(self.start)
        data["end"] = iso(self.end)
        data["generated_at"] = iso(self.generated_at)
        data["valid_until"] = iso(self.valid_until)
        data["source"] = self.source.value
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PriceSlot:
        return cls(
            start=parse_iso(data["start"]),
            end=parse_iso(data["end"]),
            value=data.get("value"),
            source=PriceSource(data["source"]),
            unit=data.get("unit", "PLN/kWh"),
            p10=data.get("p10"),
            p50=data.get("p50"),
            p90=data.get("p90"),
            confidence=data.get("confidence"),
            is_cheap=data.get("is_cheap"),
            is_expensive=data.get("is_expensive"),
            model_name=data.get("model_name"),
            generated_at=parse_iso(data["generated_at"]) if data.get("generated_at") else None,
            valid_until=parse_iso(data["valid_until"]) if data.get("valid_until") else None,
            meta=data.get("meta") or {},
        )


def _r(value: float | None, digits: int = 5) -> float | None:
    return None if value is None else round(value, digits)


@dataclass(slots=True)
class MarketPoint:
    """A raw market price observation (PLN/MWh, native resolution)."""

    start: datetime
    end: datetime
    price_pln_mwh: float
    provider: str
    product: str = "hourly"  # hourly | quarter_hour
    published_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": iso(self.start),
            "end": iso(self.end),
            "price": self.price_pln_mwh,
            "provider": self.provider,
            "product": self.product,
            "published_at": iso(self.published_at),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MarketPoint:
        return cls(
            start=parse_iso(data["start"]),
            end=parse_iso(data["end"]),
            price_pln_mwh=float(data["price"]),
            provider=data["provider"],
            product=data.get("product", "hourly"),
            published_at=parse_iso(data["published_at"]) if data.get("published_at") else None,
        )


def mwh_to_kwh(price_pln_mwh: float) -> float:
    """Convert PLN/MWh to PLN/kWh."""
    return price_pln_mwh / 1000.0


def aggregate_hourly(points: list[MarketPoint]) -> dict[datetime, float]:
    """Aggregate native-resolution market points to hourly means (UTC hour key).

    Quarter-hour products are averaged per hour only when all four quarters
    are present; partially covered hours are dropped rather than guessed.
    Hourly products take precedence over quarter-hour derived values.
    """
    hourly: dict[datetime, float] = {}
    quarters: dict[datetime, list[tuple[datetime, float]]] = {}
    for point in points:
        span = (point.end - point.start).total_seconds()
        if span >= 3600 - 1:
            hourly[floor_hour(point.start)] = point.price_pln_mwh
        else:
            quarters.setdefault(floor_hour(point.start), []).append((point.start, point.price_pln_mwh))
    for hour, items in quarters.items():
        if hour in hourly:
            continue
        unique = {start: price for start, price in items}
        if len(unique) == 4:
            hourly[hour] = sum(unique.values()) / 4
    return dict(sorted(hourly.items()))
