# Data sources, permissions and licenses

| Source | Used for | Access | Terms / notes |
|---|---|---|---|
| Pstryk `unified-metrics` | customer buy/sell prices, cheap/expensive flags, meter values, costs, balances | personal API key | <https://pstryk.pl/regulamin-api>: private, non-commercial; 3 req/h for heavy endpoints; no scraping/dumping, no mass caching, no derivative models or benchmarks, no sharing results. **This integration uses ≤ 2 req/h per key, keeps Pstryk data locally for 14 days, never trains on it, never publishes it outside your MQTT broker.** |
| ENTSO-E Transparency (A44) | day-ahead price history and publication | free token | ENTSO-E terms of use; attribution “ENTSO-E Transparency Platform”. |
| PSE API v2 (`pk5l-wp`, `kse-load`, `his-wlk-cal`, `rce-pln`) | system demand/wind/PV forecasts (≈7 days), RCE proxy | public | PSE S.A. data – attribution “Źródło: PSE S.A.”. RCE ≠ RDN. |
| TGE RDN website | Fixing I/II prices (experimental, opt-in) | public HTML | Check TGE terms before enabling; no redistribution; minimal requests. |
| Open-Meteo | local and national weather, historical forecasts | public | Non-commercial use free; attribution “Weather data by Open-Meteo.com” (CC BY 4.0). Models: ECMWF, DWD ICON, NOAA GFS. |

## Live verification (2026-10-17)

| Source | Result |
|---|---|
| Pstryk OpenAPI schema (`/integrations/schema/`) | unchanged; only `unified-metrics` documented; invalid key → HTTP 403 (handled as auth error), 404 → “no active contract” |
| Pstryk pricing fields (`price_gross`, `price_prosumer_gross`, `is_cheap`, `is_expensive`) | **not in the official schema** – confirmed only by community integrations; needs a check with a real key (the parser treats them as optional and reports seen fields in diagnostics) |
| PSE `pk5l-wp`, `rce-pln`, `his-wlk-cal` | live data parsed; plan covers ≈ 8 days ahead |
| Open-Meteo forecast (ECMWF, ICON, GFS, best match), historical forecast | live data parsed, no missing variables |
| ENTSO-E | endpoint live; invalid token → 401 handled; real A44 document not tested (no token) |
| TGE RDN page | live table parsed: 24 hourly + 96 quarter-hour prices for Fixing I and II; hourly Fixing I = mean of the 4 quarters |

## What is stored locally (`.storage/pstryk_ai.<entry>.*`)
* market: hourly market prices per provider (configurable history, default 365 days + margin), last 3 days of 15-minute points;
* system: PSE plan values; weather: national weather features (archived forecasts);
* forecasts: up to 120 forecast snapshots + live error statistics;
* state: model parameters and backtest metrics, runtime controls, last 14 days of confirmed Pstryk buy prices, 14 days of buffer decisions;
* cache: last good Pstryk/weather payloads and the Pstryk request budget.

Nothing is uploaded anywhere. Removing the integration deletes these files.

## Repository hygiene
The public repository contains no API keys, no downloaded private data and no model trained on Pstryk data. Test fixtures are either
synthetic (Pstryk) or small public samples (PSE, Open-Meteo).
