# Changelog

All notable changes are documented here. The project follows [Semantic Versioning](https://semver.org/).

## [0.1.0] – 2026-10-16
### Added
- Pstryk `unified-metrics` client: buy/sell prices, Pstryk cheap/expensive flags, meter values, costs, daily/monthly balances;
  shared, persisted request budget (≤ 2 req/h per key), `Retry-After` handling, placeholder detection, last-good cache.
- ENTSO-E A44 (PT15M/PT60M, A03), PSE API v2 (`pk5l-wp`, `kse-load`, `his-wlk-cal`, `rce-pln`), experimental TGE RDN parser.
- Open-Meteo local and national weather (9 regions, multi-model disagreement), historical forecasts import.
- Forecasting: seasonal baseline, per-horizon ridge models, backtest-gated ensemble, P10/P50/P90, confidence, rolling-origin backtesting,
  forecast snapshots and live accuracy.
- Unified price timeline with source precedence; tariff model (VAT, margin, excise, distribution, opt-in calibration).
- Optimisation: cheapest/most expensive windows, cheapest N hours, uncertainty-aware postponement, DP device scheduler,
  thermal buffer MPC with COP model.
- Home Assistant: multi-step config flow, options menu, reauth, Polish entity names, sensors/binary sensors/switches/numbers/selects/
  buttons, services, events, diagnostics, repairs.
- MQTT: versioned topics, per-day forecast topics, retained data with validity, expiring non-retained control topic, discovery, EVCC.
- Documentation (EN/PL), dashboards, Loxone/Node-RED/automation examples, 89 automated tests (Home Assistant 2026.2 and 2026.10).
