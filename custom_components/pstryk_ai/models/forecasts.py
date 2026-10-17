"""Forecast result models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .price_slot import iso, parse_iso


@dataclass(slots=True)
class ForecastPoint:
    """Market price forecast for one hour (PLN/MWh)."""

    forecast_for: datetime
    predicted_price: float
    prediction_p10: float
    prediction_p50: float
    prediction_p90: float
    model_name: str
    model_version: str
    forecast_created_at: datetime
    forecast_horizon_hours: int
    data_sources: list[str] = field(default_factory=list)
    confidence: float = 0.0
    quality_status: str = "ok"

    def to_dict(self) -> dict[str, Any]:
        return {
            "forecast_for": iso(self.forecast_for),
            "predicted_price": round(self.predicted_price, 3),
            "prediction_p10": round(self.prediction_p10, 3),
            "prediction_p50": round(self.prediction_p50, 3),
            "prediction_p90": round(self.prediction_p90, 3),
            "model_name": self.model_name,
            "model_version": self.model_version,
            "forecast_created_at": iso(self.forecast_created_at),
            "forecast_horizon_hours": self.forecast_horizon_hours,
            "data_sources": list(self.data_sources),
            "confidence": round(self.confidence, 3),
            "quality_status": self.quality_status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ForecastPoint:
        return cls(
            forecast_for=parse_iso(data["forecast_for"]),
            predicted_price=data["predicted_price"],
            prediction_p10=data["prediction_p10"],
            prediction_p50=data["prediction_p50"],
            prediction_p90=data["prediction_p90"],
            model_name=data["model_name"],
            model_version=data["model_version"],
            forecast_created_at=parse_iso(data["forecast_created_at"]),
            forecast_horizon_hours=data["forecast_horizon_hours"],
            data_sources=data.get("data_sources", []),
            confidence=data.get("confidence", 0.0),
            quality_status=data.get("quality_status", "ok"),
        )


@dataclass(slots=True)
class ForecastRun:
    """A complete forecast issued at ``created_at``."""

    created_at: datetime
    points: list[ForecastPoint]
    model_name: str
    model_version: str
    market_reference: str
    inputs_missing: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "created_at": iso(self.created_at),
            "model_name": self.model_name,
            "model_version": self.model_version,
            "market_reference": self.market_reference,
            "inputs_missing": self.inputs_missing,
            "points": [p.to_dict() for p in self.points],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ForecastRun:
        return cls(
            created_at=parse_iso(data["created_at"]),
            points=[ForecastPoint.from_dict(p) for p in data.get("points", [])],
            model_name=data.get("model_name", "unknown"),
            model_version=data.get("model_version", "0"),
            market_reference=data.get("market_reference", "unknown"),
            inputs_missing=data.get("inputs_missing", []),
        )


@dataclass(slots=True)
class HorizonMetrics:
    """Backtest metrics for one forecast day (1..7)."""

    day: int
    samples: int = 0
    mae: float | None = None
    rmse: float | None = None
    median_ae: float | None = None
    interval_coverage: float | None = None
    cheapest_window_hit_rate: float | None = None
    cheapest_window_regret: float | None = None
    savings_vs_naive: float | None = None
    baseline_mae: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {k: getattr(self, k) for k in self.__slots__}  # type: ignore[attr-defined]
