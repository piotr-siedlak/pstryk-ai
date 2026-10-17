"""Forecast confidence and prediction-interval helpers.

Confidence is a heuristic score in [0, 1] (not a probability). It decreases
with forecast horizon, recent market volatility, weather-model disagreement,
missing inputs and poor recent backtest skill. Every factor is exposed in the
diagnostics so the number is explainable.
"""

from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(slots=True)
class ConfidenceInputs:
    horizon_day: int
    volatility_ratio: float = 1.0  # recent std / long-term std
    wind_model_spread: float | None = None  # 0..~0.5 (power-index std)
    missing_inputs: int = 0
    skill: float | None = None  # 1 - mae_model / mae_naive (from backtests)


def confidence_score(inp: ConfidenceInputs) -> tuple[float, dict[str, float]]:
    horizon = math.exp(-0.12 * max(0, inp.horizon_day - 1))
    volatility = 1.0 / (1.0 + max(0.0, inp.volatility_ratio - 1.0))
    spread = 1.0 - min(0.5, 2.0 * (inp.wind_model_spread or 0.0))
    missing = 0.85**inp.missing_inputs
    skill = 0.75 if inp.skill is None else min(1.0, max(0.3, 0.6 + inp.skill))
    factors = {
        "horizon": horizon,
        "volatility": volatility,
        "weather_agreement": spread,
        "inputs": missing,
        "skill": skill,
    }
    score = horizon * volatility * spread * missing * skill
    return max(0.0, min(1.0, score)), factors


def default_interval(level: float, horizon_day: int) -> tuple[float, float]:
    """Fallback residual quantiles (PLN/MWh) when no backtest data exist."""
    half = (0.12 * abs(level) + 40.0) * math.sqrt(max(1, horizon_day))
    return -half, half


def widen_interval(q10: float, q90: float, factor: float) -> tuple[float, float]:
    return q10 * factor, q90 * factor
