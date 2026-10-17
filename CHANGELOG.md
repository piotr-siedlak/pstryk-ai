# Changelog

All notable changes are documented here. The project follows [Semantic Versioning](https://semver.org/).

## [0.4.0] – 2026-10-17
All new features are optional and switchable (options; most also with runtime switches).
### Added
- Buffer **top/bottom** temperature sensors (MQTT topic or HA entity); automatic migration of the former buffer sensor to *top*
  (config entry 1.1 → 1.2); stratification-aware comfort; charge % and stored energy.
- **Auxiliary heaters** for buffer and CWU: electric or gas, power steps, efficiency, gas price, max temperature, command topic
  (`1/0` or kW, control mode only), state topic for metering; combined heat-pump + heater optimisation by cost of delivered heat.
- **Hot-water tank (CWU)**: second storage with top/bottom sensors, ready times, daily use profile, shared heat pump with switching
  valve and priority, valve command topic, **legionella** cycle.
- **Connection power limit** across heat pump, heaters and device schedules.
- **Distribution tariff zones** (G11/G12/G12w/G13) and optimisation on the all-in price; zone sensor.
- **PV self-consumption** (production forecast from radiation, surplus valued at the sell price).
- **Learning** of building demand, storage losses, hot-water profile and COP; measured heat-pump/heater consumption and cost.
- **Pstryk spending**: yesterday, previous month, last 12 months (monthly history), average daily cost, month projection, breakdown;
  MQTT `spends/*`; optional import into HA long-term statistics.
- **Notifications** (tomorrow's prices, negative prices, local-control fallback, stale data) and MQTT **heartbeat**.
- Panel: storage cards with layer bar, heater/valve state, legionella, separate timeline lanes (heat pump → buffer/CWU, heaters, PV),
  spending section with daily/monthly charts.
### Changed
- Storage optimiser generalised (heat-pump availability per hour, heater stages, power cap, ready/legionella constraints, PV pricing);
  heavy planning runs in an executor thread.
- Daily totals sensors use `total_increasing` (Energy dashboard compatible).

## [0.3.0] – 2026-10-17
### Added
- **Temperatures from exact MQTT topics**: buffer temperature, outdoor temperature (options *Thermal buffer*) and per-device values
  (`temperature_topic` / `value_topic` + `target` in device profiles). Plain-number or JSON payloads (`temperature_key`, dotted paths),
  plausibility limits, configurable maximum age (default 30 min).
- MQTT readings take precedence over Home Assistant sensors; a stale or missing buffer reading puts the buffer in local-control fallback.
- Automatic re-planning when the buffer deviates > 1 K from the plan or a device crosses its target (≤ 1 per 5 min, deferred not dropped).
- Devices at or above their target are not scheduled ("Cel osiągnięty").
- Sensors *Temperatura bufora (odczyt)*, *Temperatura zewnętrzna (odczyt)*; panel shows the measured buffer temperature and its source,
  and device value vs target; repair issue when MQTT inputs are configured without MQTT.

## [0.2.0] – 2026-10-17
### Added
- **Pstryk AI sidebar panel**: current price with source, 48 h plan (prices, cheapest window, buffer heating and device schedules on one
  timeline), 7-day forecast with P10–P90 and daily summaries, buffer decision with temperature trajectory, devices, meter and balance,
  forecast quality, data-source status. Light/dark/mobile. Option *Panel* to hide it.
- **Configurable MQTT topics**: every topic can be renamed (relative or absolute) or disabled in *Configure → MQTT topics*; retained
  messages on old topics are removed automatically; discovery follows the new names.

### Changed
- Daily/monthly Pstryk balance is fetched once at first start (when nothing is cached), so monthly sensors are filled immediately.
- Buffer recommendation text shows local time ("od 10:00") instead of an ISO timestamp.

## [0.1.1] – 2026-10-17
### Fixed
- Pstryk HTTP 404 (meter missing / no active contract) now shows a dedicated setup error instead of "cannot connect".
- MQTT publishing on Home Assistant releases without MQTT v5 message expiry (2026.2).
- Config-flow descriptions accepted by hassfest; tests independent of time of day.

### Verified
- Live API re-check on 2026-10-17 (see docs/API_SOURCES.md).

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
