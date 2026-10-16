"""Forecast orchestration: training, model selection (Model C), inference.

The forecaster predicts the hourly *market* day-ahead price (PLN/MWh) for a
rolling 168-hour horizon. Conversion to the customer's Pstryk price happens in
the tariff layer (``tariff.py``); Pstryk prices are never used for training.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import logging
from statistics import fmean, pstdev
from typing import Any

from ..models.forecasts import ForecastPoint, ForecastRun
from .backtesting import BacktestResult, ensemble_weights, run_backtest
from .baseline import BaselineModel
from .confidence import ConfidenceInputs, confidence_score, default_interval
from .features import (
    MAX_HORIZON_DAYS,
    FeatureContext,
    build_features,
    horizon_day,
    last_complete_day,
    local_date,
)
from .price_predictor import RidgeModel, fit_ridge, quantile

_LOGGER = logging.getLogger(__name__)

ENSEMBLE_NAME = "ensemble"
MANAGER_VERSION = "1"


@dataclass
class ModelState:
    """Persistable trained state."""

    ridge: dict[int, RidgeModel] = field(default_factory=dict)
    weights: dict[int, float] = field(default_factory=dict)
    quantiles: dict[str, dict[int, tuple[float, float]]] = field(default_factory=dict)
    backtest: dict[str, Any] = field(default_factory=dict)
    trained_at: str | None = None
    market_reference: str = "unknown"
    training_samples: int = 0
    training_range: tuple[str, str] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "ridge": {str(k): m.to_dict() for k, m in self.ridge.items()},
            "weights": {str(k): w for k, w in self.weights.items()},
            "quantiles": {name: {str(k): list(v) for k, v in per.items()} for name, per in self.quantiles.items()},
            "backtest": self.backtest,
            "trained_at": self.trained_at,
            "market_reference": self.market_reference,
            "training_samples": self.training_samples,
            "training_range": list(self.training_range) if self.training_range else None,
            "version": MANAGER_VERSION,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ModelState:
        if data.get("version") != MANAGER_VERSION:
            return cls()
        return cls(
            ridge={int(k): RidgeModel.from_dict(v) for k, v in (data.get("ridge") or {}).items()},
            weights={int(k): float(v) for k, v in (data.get("weights") or {}).items()},
            quantiles={
                name: {int(k): (v[0], v[1]) for k, v in per.items()}
                for name, per in (data.get("quantiles") or {}).items()
            },
            backtest=data.get("backtest") or {},
            trained_at=data.get("trained_at"),
            market_reference=data.get("market_reference", "unknown"),
            training_samples=data.get("training_samples", 0),
            training_range=tuple(data["training_range"]) if data.get("training_range") else None,
        )


class PriceForecaster:
    def __init__(self, mode: str = "auto", alpha: float = 1e-3) -> None:
        self.mode = mode
        self.alpha = alpha
        self.baseline = BaselineModel()
        self.state = ModelState()

    # ------------------------------------------------------------------ train
    def train(
        self,
        ctx: FeatureContext,
        *,
        market_reference: str,
        now: datetime,
        backtest_origins: int = 60,
    ) -> ModelState:
        """Fit ridge models per horizon and evaluate everything with a backtest.

        CPU-bound — call from an executor thread.
        """
        state = ModelState(market_reference=market_reference, trained_at=now.isoformat())
        hours = sorted(ctx.prices)
        if len(hours) < 24 * 30:
            _LOGGER.info("Not enough market history for ML (%d hours); baseline only", len(hours))
            self.state = state
            return state
        first_day = local_date(hours[0])
        per_k: dict[int, list[tuple[list[float], float]]] = {k: [] for k in range(1, MAX_HORIZON_DAYS + 1)}
        for t in hours:
            for k in per_k:
                known = local_date(t) - timedelta(days=k)
                if known < first_day + timedelta(days=7):
                    continue
                x = build_features(t, known, ctx)
                if x is not None:
                    per_k[k].append((x, ctx.prices[t]))
        for k, samples in per_k.items():
            if len(samples) < 24 * 21:
                continue
            try:
                state.ridge[k] = fit_ridge(samples, self.alpha)
            except ValueError as err:
                _LOGGER.debug("Ridge k=%s failed: %s", k, err)
        state.training_samples = sum(len(s) for s in per_k.values())
        state.training_range = (hours[0].isoformat(), hours[-1].isoformat())

        bt: BacktestResult = run_backtest(ctx, origins=backtest_origins, alpha=self.alpha)
        state.weights = ensemble_weights(bt)
        state.quantiles = dict(bt.residual_quantiles)
        # ensemble residual quantiles (post-hoc; documented as slightly optimistic)
        ens: dict[int, list[float]] = {}
        ens_err: dict[int, list[float]] = {}
        for p in bt.predictions:
            w = state.weights.get(p.k, 0.0)
            pred = p.baseline if p.ridge is None else (1 - w) * p.baseline + w * p.ridge
            ens.setdefault(p.k, []).append(p.actual - pred)
            ens_err.setdefault(p.k, []).append(abs(p.actual - pred))
        state.quantiles[ENSEMBLE_NAME] = {
            k: (quantile(v, 0.1), quantile(v, 0.9)) for k, v in ens.items() if len(v) >= 24
        }
        summary = bt.summary()
        summary["metrics"][ENSEMBLE_NAME] = {
            str(k): {"day": k, "samples": len(v), "mae": round(fmean(v), 2)} for k, v in ens_err.items()
        }
        summary["weights"] = {str(k): w for k, w in state.weights.items()}
        state.backtest = summary
        self.state = state
        return state

    # --------------------------------------------------------------- predict
    def _skill(self, k: int, model: str) -> float | None:
        metrics = (self.state.backtest.get("metrics") or {}).get(model, {}).get(str(k))
        base = (self.state.backtest.get("metrics") or {}).get("baseline", {}).get(str(k))
        if not metrics or not base or not base.get("mae"):
            return None
        naive = base.get("mae")
        return 1.0 - metrics["mae"] / naive if model != "baseline" else 0.0

    def forecast(
        self,
        ctx: FeatureContext,
        now: datetime,
        *,
        horizon_hours: int = 168,
        sources: list[str] | None = None,
        known_until: datetime | None = None,
    ) -> ForecastRun:
        """Forecast every hour from the current hour that is not yet known."""
        last_known: date | None = last_complete_day(ctx.prices, known_until)
        start = now.replace(minute=0, second=0, microsecond=0)
        points: list[ForecastPoint] = []
        missing: list[str] = []
        if last_known is None:
            return ForecastRun(now, [], "none", MANAGER_VERSION, self.state.market_reference, ["market_history"])

        recent = [v for h, v in ctx.prices.items() if h >= start - timedelta(days=3)]
        longer = [v for h, v in ctx.prices.items() if h >= start - timedelta(days=28)]
        vol_ratio = (
            (pstdev(recent) / pstdev(longer)) if len(recent) > 24 and len(longer) > 48 and pstdev(longer) > 0 else 1.0
        )

        for i in range(horizon_hours):
            t = start + timedelta(hours=i)
            if t in ctx.prices:
                continue  # published market price exists; not a forecast slot
            k_raw = horizon_day(t, last_known)
            if k_raw < 1:
                continue
            k = min(k_raw, MAX_HORIZON_DAYS)
            base = self.baseline.predict(t, last_known, ctx.prices)
            if base is None:
                continue
            ridge_model = self.state.ridge.get(k)
            x = build_features(t, last_known, ctx) if ridge_model is not None else None
            ridge = ridge_model.predict(x) if (ridge_model is not None and x is not None) else None

            if self.mode == "baseline" or ridge is None:
                pred, name, qkey = base, BaselineModel.name, "baseline"
            elif self.mode == "ridge":
                pred, name, qkey = ridge, "ridge_horizon", "ridge"
            else:
                w = self.state.weights.get(k, 0.0)
                if w <= 0:
                    pred, name, qkey = base, BaselineModel.name, "baseline"
                else:
                    pred, name, qkey = (1 - w) * base + w * ridge, ENSEMBLE_NAME, ENSEMBLE_NAME

            q = self.state.quantiles.get(qkey, {}).get(k)
            q10, q90 = q if q else default_interval(pred, k)
            if k_raw > MAX_HORIZON_DAYS:
                q10, q90 = q10 * 1.3, q90 * 1.3

            n_missing = 0
            sys_row = ctx.system.get(t)
            if sys_row is None or getattr(sys_row, "demand_mw", None) is None:
                n_missing += 1
                if "pse_system_forecast" not in missing:
                    missing.append("pse_system_forecast")
            w_row = ctx.weather.get(t)
            if w_row is None or w_row.get("national_temperature") is None:
                n_missing += 1
                if "national_weather" not in missing:
                    missing.append("national_weather")
            spread = w_row.get("wind_model_spread") if w_row is not None else None
            conf, _ = confidence_score(
                ConfidenceInputs(
                    horizon_day=k_raw,
                    volatility_ratio=vol_ratio,
                    wind_model_spread=spread,
                    missing_inputs=n_missing if name != BaselineModel.name else 0,
                    skill=self._skill(k, qkey),
                )
            )
            points.append(
                ForecastPoint(
                    forecast_for=t,
                    predicted_price=pred,
                    prediction_p10=pred + q10,
                    prediction_p50=pred,
                    prediction_p90=pred + q90,
                    model_name=name,
                    model_version=MANAGER_VERSION,
                    forecast_created_at=now,
                    forecast_horizon_hours=int((t - start).total_seconds() // 3600),
                    data_sources=list(sources or []),
                    confidence=conf,
                    quality_status="stale_inputs" if k_raw > MAX_HORIZON_DAYS else "ok",
                )
            )
        model_names = {p.model_name for p in points}
        run_name = model_names.pop() if len(model_names) == 1 else "mixed"
        return ForecastRun(now, points, run_name, MANAGER_VERSION, self.state.market_reference, missing)


def merge_hourly(*series: Mapping[datetime, float]) -> dict[datetime, float]:
    """Merge hourly series; later arguments take precedence."""
    out: dict[datetime, float] = {}
    for s in series:
        out.update(s)
    return dict(sorted(out.items()))
