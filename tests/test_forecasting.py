"""Forecasting engine: features, leakage, baseline, ridge, backtest, timeline precedence."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
import math
import random

import pytest

from custom_components.pstryk_ai.forecasting.backtesting import (
    cheapest_window_start,
    ensemble_weights,
    run_backtest,
)
from custom_components.pstryk_ai.forecasting.baseline import BaselineModel
from custom_components.pstryk_ai.forecasting.confidence import ConfidenceInputs, confidence_score
from custom_components.pstryk_ai.forecasting.features import (
    FEATURE_NAMES,
    FeatureContext,
    build_features,
    day_type,
    easter,
    is_holiday,
    last_complete_day,
    local_date,
)
from custom_components.pstryk_ai.forecasting.model_manager import ModelState, PriceForecaster
from custom_components.pstryk_ai.forecasting.price_predictor import NormalEquations, fit_ridge, solve_linear
from custom_components.pstryk_ai.models.price_slot import PriceSlot, PriceSource
from custom_components.pstryk_ai.tariff import Tariff
from custom_components.pstryk_ai.timeline import build_timeline

from .conftest import local_midnight_utc, synthetic_market


def test_polish_holidays() -> None:
    assert easter(2026) == date(2026, 4, 5)
    assert is_holiday(date(2026, 11, 11))
    assert is_holiday(date(2026, 6, 4))  # Corpus Christi 2026
    assert is_holiday(date(2025, 12, 24))  # Christmas Eve is a holiday since 2025
    assert not is_holiday(date(2024, 12, 24))
    assert day_type(date(2026, 10, 17)) == 1  # Saturday
    assert day_type(date(2026, 11, 11)) == 2


def test_features_do_not_leak_future_prices(market_history: dict) -> None:
    target = local_midnight_utc(2026, 9, 10) + timedelta(hours=15)
    known_day = local_date(target) - timedelta(days=2)
    ctx = FeatureContext(market_history, {}, {})
    x1 = build_features(target, known_day, ctx)
    # corrupt everything after the known day -> features must not change
    cutoff = local_midnight_utc(known_day.year, known_day.month, known_day.day) + timedelta(days=1)
    corrupted = {h: (v if h < cutoff else 9999.0) for h, v in market_history.items()}
    x2 = build_features(target, known_day, FeatureContext(corrupted, {}, {}))
    assert x1 is not None and x1 == x2
    assert len(x1) == len(FEATURE_NAMES)


def test_features_flag_missing_inputs(market_history: dict) -> None:
    target = local_midnight_utc(2026, 9, 10) + timedelta(hours=10)
    x = build_features(target, local_date(target) - timedelta(days=1), FeatureContext(market_history, {}, {}))
    assert x[FEATURE_NAMES.index("pse_missing")] == 1.0
    assert x[FEATURE_NAMES.index("weather_missing")] == 1.0


def test_features_on_dst_days(market_history: dict) -> None:
    for y, m, d in ((2026, 3, 29), (2025, 10, 26)):
        start = local_midnight_utc(y, m, d)
        for h in range(23 if m == 3 else 25):
            t = start + timedelta(hours=h)
            if t not in market_history:
                continue
            x = build_features(t, local_date(t) - timedelta(days=1), FeatureContext(market_history, {}, {}))
            assert x is not None


def test_last_complete_day(market_history: dict) -> None:
    last = max(market_history)
    assert last_complete_day(market_history) == local_date(last) - timedelta(
        days=0 if local_date(last + timedelta(hours=1)) != local_date(last) else 1
    )


def test_solve_linear_and_ridge_recovers_linear_model() -> None:
    assert solve_linear([[2.0, 1.0], [1.0, 3.0]], [3.0, 5.0]) == pytest.approx([0.8, 1.4])
    rnd = random.Random(0)
    samples = []
    for _ in range(400):
        a, b = rnd.uniform(-1, 1), rnd.uniform(0, 5)
        samples.append(([1.0, a, b], 10 + 3 * a - 2 * b))
    model = fit_ridge(samples, alpha=1e-6)
    assert model.coef == pytest.approx([10, 3, -2], abs=1e-3)
    assert model.train_mae < 1e-4


def test_normal_equations_incremental_equals_batch() -> None:
    rnd = random.Random(1)
    rows = [([1.0, rnd.random(), rnd.random()], rnd.random()) for _ in range(200)]
    ne = NormalEquations(3)
    for x, y in rows:
        ne.add(x, y)
    assert ne.solve(1e-3).coef == pytest.approx(fit_ridge(rows, 1e-3).coef)


def test_baseline_tracks_daily_profile(market_history: dict) -> None:
    target = local_midnight_utc(2026, 9, 20) + timedelta(hours=19)
    known = local_date(target) - timedelta(days=1)
    pred = BaselineModel().predict(target, known, market_history)
    assert pred is not None
    assert abs(pred - market_history[target]) < 150


def test_backtest_metrics_per_horizon_and_model_selection(market_history: dict) -> None:
    hist = {k: v for k, v in market_history.items() if k < datetime(2026, 1, 15, tzinfo=UTC)}
    result = run_backtest(FeatureContext(hist, {}, {}), origins=20, min_train_days=40)
    assert result.origins >= 20
    for model in ("baseline", "ridge"):
        assert set(result.metrics[model]) == set(range(1, 8))
        for m in result.metrics[model].values():
            assert m.mae is not None and m.rmse >= m.mae >= 0
            assert 0 <= m.interval_coverage <= 1
            assert m.cheapest_window_regret is None or m.cheapest_window_regret >= 0
    weights = ensemble_weights(result)
    for k, w in weights.items():
        ridge, base = result.metrics["ridge"][k], result.metrics["baseline"][k]
        if w > 0:
            assert ridge.mae < base.mae  # ridge only used when it is better out-of-sample


def test_cheapest_window_start() -> None:
    assert cheapest_window_start([5, 4, 1, 1, 1, 9], 3) == 2
    assert cheapest_window_start([1, 2], 3) is None


def test_confidence_decreases_with_horizon_and_volatility() -> None:
    c1, _ = confidence_score(ConfidenceInputs(horizon_day=1))
    c7, _ = confidence_score(ConfidenceInputs(horizon_day=7))
    cv, _ = confidence_score(ConfidenceInputs(horizon_day=1, volatility_ratio=2.0))
    cm, _ = confidence_score(ConfidenceInputs(horizon_day=1, missing_inputs=2))
    cs, _ = confidence_score(ConfidenceInputs(horizon_day=1, wind_model_spread=0.2))
    cb, _ = confidence_score(ConfidenceInputs(horizon_day=1, skill=-0.5))
    assert c1 > c7 and c1 > cv and c1 > cm and c1 > cs and c1 > cb


@pytest.fixture(scope="module")
def trained() -> tuple[PriceForecaster, FeatureContext, datetime]:
    hist = synthetic_market(datetime(2025, 9, 1, tzinfo=UTC), 24 * 200)
    now = max(hist) - timedelta(hours=10)
    known = {k: v for k, v in hist.items() if local_date(k) <= local_date(now)}
    ctx = FeatureContext(known, {}, {})
    f = PriceForecaster()
    f.train(ctx, market_reference="synthetic", now=now, backtest_origins=20)
    return f, ctx, now


def test_forecast_168h_rolling_with_required_fields(trained) -> None:
    f, ctx, now = trained
    run = f.forecast(ctx, now, horizon_hours=168, sources=["synthetic"])
    assert run.points, "forecast must not be empty"
    last = max(p.forecast_for for p in run.points)
    assert last - now.replace(minute=0, second=0, microsecond=0) <= timedelta(hours=167)
    first = run.points[0].to_dict()
    for key in (
        "predicted_price",
        "prediction_p10",
        "prediction_p50",
        "prediction_p90",
        "model_name",
        "model_version",
        "forecast_created_at",
        "forecast_for",
        "forecast_horizon_hours",
        "data_sources",
        "confidence",
        "quality_status",
    ):
        assert key in first
    for p in run.points:
        assert p.prediction_p10 <= p.prediction_p50 <= p.prediction_p90
        assert 0 <= p.confidence <= 1
    # no forecast for hours with a known market price
    assert all(p.forecast_for not in ctx.prices for p in run.points)


def test_model_state_roundtrip(trained) -> None:
    f, _, _ = trained
    restored = ModelState.from_dict(f.state.to_dict())
    assert restored.weights == f.state.weights
    assert set(restored.ridge) == set(f.state.ridge)


def test_forecast_regeneration_is_deterministic(trained) -> None:
    f, ctx, now = trained
    a = f.forecast(ctx, now)
    b = f.forecast(ctx, now)
    assert [p.prediction_p50 for p in a.points] == [p.prediction_p50 for p in b.points]


def test_baseline_mode_when_no_model(trained) -> None:
    _, ctx, now = trained
    f = PriceForecaster(mode="auto")  # untrained
    run = f.forecast(ctx, now)
    assert run.points and {p.model_name for p in run.points} == {"seasonal_baseline"}


def test_timeline_precedence_and_forecast_replacement(trained) -> None:
    f, ctx, now = trained
    run = f.forecast(ctx, now)
    tariff = Tariff(vat_rate=0.23, energy_margin_net=0.02, excise_net=0.005)
    tl = build_timeline(now, pstryk_buy=[], pstryk_sell=[], market_hourly={}, forecast=run, tariff=tariff)
    tomorrow_slots = [s for s in tl.buy if local_date(s.start) == local_date(now) + timedelta(days=1)]
    assert tomorrow_slots and all(s.source.is_forecast for s in tomorrow_slots)
    # confirmed Pstryk prices arrive for tomorrow -> they must replace the forecast
    confirmed = [PriceSlot(s.start, s.end, 0.4321, PriceSource.ACTUAL_PSTRYK) for s in tomorrow_slots]
    tl2 = build_timeline(now, pstryk_buy=confirmed, pstryk_sell=[], market_hourly={}, forecast=run, tariff=tariff)
    replaced = [s for s in tl2.buy if local_date(s.start) == local_date(now) + timedelta(days=1)]
    assert all(s.source is PriceSource.ACTUAL_PSTRYK and s.value == 0.4321 for s in replaced)
    # published market price outranks forecast but not Pstryk
    t = tomorrow_slots[0].start
    tl3 = build_timeline(now, pstryk_buy=[], pstryk_sell=[], market_hourly={t: 500.0}, forecast=run, tariff=tariff)
    slot = tl3.at(t)
    assert slot.source is PriceSource.PUBLISHED_TGE
    assert slot.value == pytest.approx((0.5 + 0.02 + 0.005) * 1.23)


def test_tariff_and_sell_price_rules() -> None:
    t = Tariff(vat_rate=0.23, energy_margin_net=0.0, excise_net=0.005, var_distribution_net=0.3)
    assert t.sell_price(-50.0) == 0.0  # negative TGE clamped (Pstryk energy_sold_value rule)
    assert t.sell_price(400.0) == pytest.approx(0.4 * 1.23)
    assert t.all_in(1.0) == pytest.approx(1.0 + 0.3 * 1.23)
    t.pstryk_includes_distribution = True
    assert t.all_in(1.0) == 1.0
    assert t.energy_price(-100.0) < 0  # negative prices supported
    pairs = [(m, (m / 1000 * 1.23) * 1.0 + 0.1) for m in range(100, 900, 10)]
    assert t.calibrate(pairs)
    assert t.energy_price(500) == pytest.approx(0.5 * 1.23 + 0.1, abs=1e-6)


def test_synthetic_market_has_daily_shape() -> None:
    hist = synthetic_market(datetime(2026, 1, 5, tzinfo=UTC), 48)
    assert len(hist) == 48
    assert not any(math.isnan(v) for v in hist.values())
