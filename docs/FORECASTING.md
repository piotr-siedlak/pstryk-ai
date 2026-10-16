# Forecasting

## Target and horizon
The engine forecasts the hourly **market** day-ahead price (PLN/MWh) for a rolling 168-hour horizon. Customer prices are derived through
the tariff layer. Hours with a confirmed Pstryk price or a published market price are never forecast.

*Horizon day* `k` = number of local days between the last fully known market day and the target day (`k = 1`: tomorrow before the auction).
All features are built from information available at the end of the last known day.

## Inputs
| Group | Features |
|---|---|
| Calendar | hour of day (one-hot), Saturday, Sunday/public holiday (PL incl. 24 Dec since 2025), season (sin/cos day-of-year) |
| Price history | price at the same hour `k` days earlier, mean of same hour over 7 days, mean and std of last known day |
| Power system (PSE `pk5l-wp`) | demand, wind, PV, residual load (demand − wind − PV), planned exchange (GW) |
| National weather (Open-Meteo, 9 regions) | demand-weighted temperature, heating degrees, wind power index (100 m, generic power curve), solar irradiance, model disagreement |
| Interactions | residual load × peak hour, PV × midday |

Missing groups are replaced by typical values plus a `*_missing` flag; confidence is reduced accordingly.

## Models
* **A – seasonal baseline**: similar-day hourly profile over 4 weeks + level shift damped by 0.8^k. Always available.
* **B – ridge regression**, one model per horizon day (1…7), pure Python (normal equations, standardised features). Chosen over gradient
  boosting for zero dependencies, seconds-long training on HA hardware, and stable extrapolation; heavier learners can be added as an
  optional external service later.
* **C – ensemble**: per horizon, ridge weight = inverse-squared out-of-sample MAE, **only if ridge beats the baseline** in the rolling
  backtest; otherwise the baseline is used.

Intervals P10/P90 come from empirical out-of-sample residual quantiles per horizon (fallback: ±(12 % · level + 40)·√k).
Confidence (0–1, heuristic) = horizon · volatility · weather agreement · input completeness · backtest skill.

## Backtesting
Rolling origin, expanding window: for every origin day the ridge models are refitted on targets ≤ origin, intervals use only previous
out-of-sample errors. Metrics per horizon day: MAE, RMSE, median AE, interval coverage, cheapest 3 h window hit rate (±1 h), regret
(PLN/MWh above the true cheapest window) and savings versus the baseline's window choice. Run it anytime with `pstryk_ai.run_backtest`;
results appear in *Dokładność prognoz* attributes and diagnostics. Live accuracy (stored snapshots vs later prices) is tracked separately.

## Measured results (2026-10-16, public data)
Data: PSE RCE (as price proxy – no ENTSO-E token was available for this run), PSE `pk5l-wp`, Open-Meteo historical forecasts,
2025-12-19 → 2026-10-15 (7 223 h), 97 rolling origins (≈ last 3 months), horizons 1–7 days.

| Day | Baseline MAE | Ridge MAE (price only) | **Ridge MAE (+ PSE + weather)** | Coverage P10–P90 | Window hit rate | Regret (PLN/MWh) |
|---|---|---|---|---|---|---|
| 1 | 124.6 | 116.2 | **85.2** | 0.73 | 0.93 | 6.8 |
| 2 | 132.1 | 128.7 | **90.1** | 0.74 | 0.93 | 6.0 |
| 3 | 135.4 | 131.5 | **90.4** | 0.75 | 0.94 | 5.7 |
| 4 | 135.8 | 132.6 | **91.3** | 0.75 | 0.93 | 6.0 |
| 5 | 133.1 | 136.4 | **95.0** | 0.76 | 0.95 | 6.6 |
| 6 | 131.4 | 131.8 | **94.3** | 0.75 | 0.93 | 7.3 |
| 7 | 128.8 | 127.4 | **91.5** | 0.76 | 0.94 | 6.2 |

Honest reading of these numbers:
* With system and weather inputs ridge beats the baseline by ~30 % at every horizon; with price history only it barely helps.
* **Days 2–7 are optimistic**: archived PSE plans and Open-Meteo historical forecasts are short-lead values, while live forecasts for day
  5–7 will be less accurate. Live accuracy (*Dokładność prognoz → live_mae*) is the number to trust after a few weeks.
* P10–P90 coverage (≈ 0.75) is slightly below the nominal 0.80 – intervals are a little narrow.
* RCE (15-min balancing-related price) is not RDN; with ENTSO-E data the absolute numbers will differ. Re-run the backtest after import.
* Window hit rate counts ±1 h as a hit; regret is small relative to a typical daily price spread, which matters more for scheduling
  than the absolute price error.

## Structural changes
The 15-minute market (2025/2026) changed price shapes; the expanding window and weekly retraining adapt, and the backtest only reports what
happened on recent origins. Hourly and quarter-hour data are not mixed: training uses hourly means built from complete quarters.
