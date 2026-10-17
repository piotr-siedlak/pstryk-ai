# Data sources, permissions and licenses

| Source | Used for | Access | Terms / notes |
|---|---|---|---|
| Pstryk `unified-metrics` | customer buy/sell prices, cheap/expensive flags, meter values, costs, balances | personal API key | <https://pstryk.pl/regulamin-api>: private, non-commercial; 3 req/h for heavy endpoints; no scraping/dumping, no mass caching, no derivative models or benchmarks, no sharing results. **This integration uses ≤ 2 req/h per key, keeps Pstryk data locally for 14 days, never trains on it, never publishes it outside your MQTT broker.** |
| ENTSO-E Transparency (A44) | day-ahead price history and publication | free token | ENTSO-E terms of use; attribution “ENTSO-E Transparency Platform”. |
| PSE API v2 (`pk5l-wp`, `kse-load`, `his-wlk-cal`, `rce-pln`) | system demand/wind/PV forecasts (≈7 days), RCE proxy | public | PSE S.A. data – attribution “Źródło: PSE S.A.”. RCE ≠ RDN. |
| TGE RDN website | Fixing I/II prices (experimental, opt-in) | public HTML | Check TGE terms before enabling; no redistribution; minimal requests. |
| Open-Meteo | local and national weather, historical forecasts | public | Non-commercial use free; attribution “Weather data by Open-Meteo.com” (CC BY 4.0). Models: ECMWF, DWD ICON, NOAA GFS. |

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
