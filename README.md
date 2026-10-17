# Pstryk AI – Energy Intelligence & Optimization

[![hacs](https://img.shields.io/badge/HACS-Custom-41BDF5.svg)](https://hacs.xyz) ![version](https://img.shields.io/badge/version-0.1.0-blue)

Home Assistant integration for Polish [Pstryk.pl](https://pstryk.pl) customers. It combines **confirmed Pstryk prices** with public market,
power-system and weather data to build a **rolling 7-day (168 h) probabilistic price forecast**, finds the cheapest periods, plans flexible
loads and a **heat-pump buffer**, and publishes everything to Home Assistant and **MQTT** (Loxone, Node-RED, ioBroker, EVCC).

🇵🇱 Pełna dokumentacja po polsku: [README_PL.md](README_PL.md)

> **Pstryk is the primary source of actual customer prices.** Market data (ENTSO-E / TGE / PSE) and weather only fill the future and
> drive the forecast. A forecast is never presented as a confirmed price.

## Features
* Pstryk `unified-metrics` API: buy/sell prices, Pstryk cheap/expensive flags, import/export, costs, daily & monthly balances.
  Budget of ≤ 2 requests/hour per key (limit is 3), persisted across restarts, `Retry-After` honoured, placeholder detection for tomorrow.
* Market data: ENTSO-E day-ahead (15-min & hourly), PSE API v2 (7-day demand/wind/PV plan, RCE kept separate), optional TGE RDN page.
* Weather: Open-Meteo (ECMWF / ICON / GFS) for the building **and** for 9 representative regions of Poland (wind & solar indices,
  model disagreement), historical forecasts for honest training.
* Forecast: seasonal baseline + horizon-specific ridge models + ensemble that is used **only when the rolling backtest shows it helps**;
  P10/P50/P90, confidence, live accuracy tracking.
* Optimisation: cheapest windows across midnight/days, cheapest N hours, most expensive periods, uncertainty-aware postponement,
  device profiles with min run/off times (dynamic programming), thermal buffer MPC with COP(T_out, T_supply) and heat losses.
* Event-aware scheduler: 00:05 rollover, 06:00/18:00 weather, 10:45 Fixing I, **13:00 main calculation**, retries until Pstryk confirms,
  14:05 Fixing II, sensor updates exactly at slot boundaries without API calls.
* MQTT: versioned JSON + scalar topics, per-day forecast topics, retained data with `valid_until`, non-retained expiring control topic,
  optional discovery and EVCC topic.
* Polish UI (entity names), English/Polish config flow, diagnostics with redaction, repairs, services, native dashboard.

## Measured forecast quality
Rolling-origin backtest on public data (97 origins, 2026): MAE ≈ 85–95 PLN/MWh for days 1–7 with PSE + weather inputs vs 125–136 PLN/MWh
for the seasonal baseline. Read the caveats in [docs/FORECASTING.md](docs/FORECASTING.md) – days 2–7 are optimistic in backtests.

## Quick start
1. HACS → Custom repositories → `https://github.com/piotr-siedlak/pstryk-ai` (Integration) → install → restart.
2. Add integration **Pstryk AI**, paste your Pstryk API key, (recommended) an ENTSO-E token, configure MQTT/buffer.
3. Import `dashboards/pstryk_ai.yaml` as a dashboard.

## Documentation
[Installation](docs/INSTALLATION.md) · [Configuration](docs/CONFIGURATION.md) · [Architecture](docs/ARCHITECTURE.md) ·
[Data sources & licenses](docs/API_SOURCES.md) · [MQTT topics](docs/MQTT_TOPICS.md) · [Forecasting](docs/FORECASTING.md) ·
[Optimization](docs/OPTIMIZATION.md) · [Troubleshooting](docs/TROUBLESHOOTING.md) · [Research](docs/RESEARCH.md) ·
[Loxone example](examples/loxone.md) · [Changelog](CHANGELOG.md)

## Safety
The integration is **advisory by default**. It never switches heating devices itself. Any controller acting on its MQTT topics must keep
independent local safety interlocks (thermostats, over-temperature protection, manufacturer limits). Stale or missing data produce
`mode = fallback` and `should_heat = 0`, meaning *use local control*.

## Privacy & terms
Private, non-commercial use in line with the [Pstryk API terms](https://pstryk.pl/regulamin-api). Pstryk data stays local (14 days), is
never used to train models and never leaves your Home Assistant/MQTT broker. Data attributions: Pstryk, ENTSO-E Transparency Platform,
PSE S.A., TGE S.A., Open-Meteo.com (CC BY 4.0).

## Development
```bash
python3 -m venv .venv && .venv/bin/pip install pytest-homeassistant-custom-component ruff pytest-cov
.venv/bin/python -m pytest
```

Not affiliated with Pstryk, TGE, PSE or ENTSO-E. MIT License.
