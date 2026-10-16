"""Rolling-origin backtesting.

For every origin day ``D`` (the last fully known market day) and horizon
``k = 1..7`` we forecast day ``D + k`` using only information available at
the end of ``D``:

* the ridge model for ``k`` is re-fitted on samples whose targets are ≤ ``D``
  (expanding window, incremental normal equations),
* prediction intervals come from *previous* out-of-sample errors only,
* weather/system features come from the stored forecast archive (see
  docs/FORECASTING.md for the remaining optimism of archived inputs).

Metrics per horizon day: MAE, RMSE, median AE, P10–P90 coverage, cheapest
3-hour window hit rate, cheapest-window regret and savings versus the
baseline's choice.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import math
from statistics import median

from ..models.forecasts import HorizonMetrics
from .baseline import BaselineModel
from .confidence import default_interval
from .features import MAX_HORIZON_DAYS, FeatureContext, build_features, day_start_utc, local_date
from .price_predictor import NormalEquations, quantile

WINDOW_H = 3


@dataclass
class Prediction:
    target: datetime
    k: int
    actual: float
    baseline: float
    ridge: float | None
    q10: float
    q90: float


@dataclass
class BacktestResult:
    metrics: dict[str, dict[int, HorizonMetrics]] = field(default_factory=dict)
    residual_quantiles: dict[str, dict[int, tuple[float, float]]] = field(default_factory=dict)
    predictions: list[Prediction] = field(default_factory=list)
    origins: int = 0

    def summary(self) -> dict:
        return {
            "origins": self.origins,
            "metrics": {
                model: {str(k): m.to_dict() for k, m in per_k.items()} for model, per_k in self.metrics.items()
            },
            "residual_quantiles": {
                model: {str(k): list(v) for k, v in per_k.items()} for model, per_k in self.residual_quantiles.items()
            },
        }


def mae(errors: list[float]) -> float:
    return sum(abs(e) for e in errors) / len(errors)


def rmse(errors: list[float]) -> float:
    return math.sqrt(sum(e * e for e in errors) / len(errors))


def cheapest_window_start(values: list[float], width: int = WINDOW_H) -> int | None:
    if len(values) < width:
        return None
    best_i, best = None, math.inf
    for i in range(len(values) - width + 1):
        s = sum(values[i : i + width])
        if s < best:
            best_i, best = i, s
    return best_i


def _day_series(preds: list[Prediction], attr: str) -> list[float]:
    return [getattr(p, attr) for p in sorted(preds, key=lambda p: p.target)]


def compute_metrics(predictions: list[Prediction], model: str) -> dict[int, HorizonMetrics]:
    by_k: dict[int, list[Prediction]] = defaultdict(list)
    for p in predictions:
        if model == "ridge" and p.ridge is None:
            continue
        by_k[p.k].append(p)
    out: dict[int, HorizonMetrics] = {}
    for k, preds in sorted(by_k.items()):
        pred_attr = "ridge" if model == "ridge" else "baseline"
        errors = [getattr(p, pred_attr) - p.actual for p in preds]
        base_errors = [p.baseline - p.actual for p in preds]
        inside = [p.q10 <= p.actual - getattr(p, pred_attr) <= p.q90 for p in preds]
        days: dict[date, list[Prediction]] = defaultdict(list)
        for p in preds:
            days[local_date(p.target)].append(p)
        hits = regrets = savings = 0.0
        n_days = 0
        for day_preds in days.values():
            if len(day_preds) < 23:
                continue
            actual = _day_series(day_preds, "actual")
            fc = _day_series(day_preds, pred_attr)
            base = _day_series(day_preds, "baseline")
            a = cheapest_window_start(actual)
            f = cheapest_window_start(fc)
            b = cheapest_window_start(base)
            if a is None or f is None or b is None:
                continue
            best = sum(actual[a : a + WINDOW_H]) / WINDOW_H
            chosen = sum(actual[f : f + WINDOW_H]) / WINDOW_H
            base_chosen = sum(actual[b : b + WINDOW_H]) / WINDOW_H
            hits += 1.0 if abs(a - f) <= 1 else 0.0
            regrets += chosen - best
            savings += base_chosen - chosen
            n_days += 1
        out[k] = HorizonMetrics(
            day=k,
            samples=len(preds),
            mae=round(mae(errors), 2),
            rmse=round(rmse(errors), 2),
            median_ae=round(median(abs(e) for e in errors), 2),
            interval_coverage=round(sum(inside) / len(inside), 3),
            cheapest_window_hit_rate=round(hits / n_days, 3) if n_days else None,
            cheapest_window_regret=round(regrets / n_days, 2) if n_days else None,
            savings_vs_naive=round(savings / n_days, 2) if n_days else None,
            baseline_mae=round(mae(base_errors), 2),
        )
    return out


def run_backtest(
    ctx: FeatureContext,
    *,
    origins: int = 60,
    min_train_days: int = 45,
    alpha: float = 1e-3,
    horizons: int = MAX_HORIZON_DAYS,
) -> BacktestResult:
    """Rolling-origin evaluation of baseline and ridge models."""
    prices = ctx.prices
    if not prices:
        return BacktestResult()
    hours = sorted(prices)
    first_day = local_date(hours[0])
    last_day = local_date(hours[-1]) - timedelta(days=1)  # last complete-ish day
    baseline = BaselineModel()

    # Pre-compute samples per horizon: target -> (x, y)
    samples: dict[int, list[tuple[date, datetime, list[float], float]]] = {k: [] for k in range(1, horizons + 1)}
    for t in hours:
        target_day = local_date(t)
        for k in range(1, horizons + 1):
            known = target_day - timedelta(days=k)
            if known < first_day + timedelta(days=7):
                continue
            x = build_features(t, known, ctx)
            if x is not None:
                samples[k].append((target_day, t, x, prices[t]))

    first_origin = max(first_day + timedelta(days=min_train_days), last_day - timedelta(days=origins + horizons))
    result = BacktestResult()
    normal: dict[int, NormalEquations] = {}
    pointer: dict[int, int] = dict.fromkeys(samples, 0)
    oos_resid: dict[str, dict[int, list[float]]] = {"baseline": defaultdict(list), "ridge": defaultdict(list)}
    by_k_target: dict[int, dict[datetime, list[float]]] = {
        k: {t: x for _, t, x, _ in rows} for k, rows in samples.items()
    }

    origin = first_origin
    while origin + timedelta(days=1) <= last_day:
        result.origins += 1
        for k in range(1, horizons + 1):
            rows = samples[k]
            if k not in normal and rows:
                normal[k] = NormalEquations(len(rows[0][2]))
            # add every sample whose target is already known at the origin
            while pointer[k] < len(rows) and rows[pointer[k]][0] <= origin:
                _, _, x, y = rows[pointer[k]]
                normal[k].add(x, y)
                pointer[k] += 1
            model = None
            if k in normal:
                try:
                    model = normal[k].solve(alpha)
                except ValueError:
                    model = None
            target_day = origin + timedelta(days=k)
            if target_day > last_day + timedelta(days=1):
                continue
            start = day_start_utc(target_day)
            end = day_start_utc(target_day + timedelta(days=1))
            t = start
            new_resid: dict[str, list[float]] = {"baseline": [], "ridge": []}
            while t < end:
                actual = prices.get(t)
                if actual is not None:
                    b = baseline.predict(t, origin, prices)
                    x = by_k_target[k].get(t)
                    r = model.predict(x) if (model is not None and x is not None) else None
                    if b is not None:
                        ref = r if r is not None else b
                        hist = oos_resid["ridge" if r is not None else "baseline"][k]
                        if len(hist) >= 48:
                            q10, q90 = quantile(hist, 0.1), quantile(hist, 0.9)
                        else:
                            q10, q90 = default_interval(ref, k)
                        result.predictions.append(Prediction(t, k, actual, b, r, q10, q90))
                        new_resid["baseline"].append(actual - b)
                        if r is not None:
                            new_resid["ridge"].append(actual - r)
                t += timedelta(hours=1)
            for name, values in new_resid.items():
                hist = oos_resid[name][k]
                hist.extend(values)
                del hist[: -24 * 60]  # keep ~60 days of errors
        origin += timedelta(days=1)

    for model_name in ("baseline", "ridge"):
        result.metrics[model_name] = compute_metrics(result.predictions, model_name)
        result.residual_quantiles[model_name] = {
            k: (quantile(v, 0.1), quantile(v, 0.9)) for k, v in oos_resid[model_name].items() if len(v) >= 24
        }
    return result


def ensemble_weights(result: BacktestResult) -> dict[int, float]:
    """Weight of the ridge model per horizon (0 = baseline only).

    Ridge is used only when it beats the baseline out-of-sample; weights are
    inverse-squared MAE.
    """
    weights: dict[int, float] = {}
    ridge = result.metrics.get("ridge", {})
    base = result.metrics.get("baseline", {})
    for k, bm in base.items():
        rm = ridge.get(k)
        if rm is None or rm.mae is None or bm.mae is None or rm.samples < 24 * 7 or rm.mae >= bm.mae:
            weights[k] = 0.0
            continue
        wr = 1.0 / (rm.mae**2)
        wb = 1.0 / (bm.mae**2)
        weights[k] = round(wr / (wr + wb), 3)
    return weights


def to_mapping(values: Mapping[datetime, float]) -> dict[datetime, float]:
    return dict(values)
