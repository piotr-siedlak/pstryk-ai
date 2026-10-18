# Changelog

All notable changes are documented here. The project follows [Semantic Versioning](https://semver.org/).

## [0.6.0] – 2026-10-18
Heating optimiser upgrade, verified on 3 × 4 weeks of real data (winter, spring, autumn).
### Added
- **Heat-pump physics** in the model used by both strategies:
  - heat output falls in frost – new option *Moc grzewcza pompy przy −15 °C* (empty = typical −1.2 %/K below +7 °C);
  - part-load efficiency (condenser lift scales with power) and **cycling losses** below the minimum modulation (EN 14825, Cc = 0.9);
  - optional **heating curve** (*Nachylenie krzywej grzewczej*): the heat pump's setpoint and the comfort minimum follow the outdoor
    temperature.
- **Optimised boost temperature** (*Tylko doładowanie*): the planner chooses the stop temperature per hour among the configured boost
  temperature and up to three lower ones (5 K apart); `boost_target` and the setpoint command carry it; the reason names it.
- **Perfect-foresight benchmark** (`optimization.simulation.optimum`, `scripts/benchmark_heating.py`): the closed-loop full control is
  within 0.1–0.4 % of the optimum in every season.
### Changed
- Five modulation steps (e.g. 30/48/65/82/100 %) instead of three.
- The savings reference thermostat keeps the weather-dependent minimum and modulates like an inverter (conservative savings).
- Labels: *Nastawa własna pompy ciepła* (was *Domyślna temperatura docelowa*); minimum/target apply at 0 °C when a curve is set.
### Fixed
- Full control could plan with 9 kW at −20 °C and let the buffer fall below the minimum in frost (62 h in a cold January simulation,
  258 h with a heating curve); now 0 h.
### Results (vs v0.5.0, same realistic heat pump)
- Boost only: winter saving vs the heat pump alone 12.7 → 36.1 zł/4 weeks; autumn −3 % to −5 % cost.
- Full control: −3 % to −24 % cost depending on season and heating curve, no comfort violations.

## [0.5.0] – 2026-10-17
### Added
- **Heat-pump strategy** (option + runtime select *Strategia sterowania pompą*):
  - **Tylko doładowanie** (`boost`, new default) – the heat pump runs on its own and holds its setpoint; Pstryk AI only recommends
    **100 % boosts in cheap hours** (cheapest 40 % of the next 24 h or negative prices) up to the boost temperature, and only when the
    stored heat is cheaper than the heat the pump would produce later (COP at the boost temperature included). Dynamic programme
    over the storage temperature, honest reasons ("Doładowanie teraz – tania energia …", "Pompa pracuje samodzielnie – doładowanie od
    HH:MM", "… doładowanie się nie opłaca w horyzoncie"), savings vs the heat pump alone.
  - **Pełne sterowanie** (`full`) – the v0.4 hourly control with modulation.
  - Options: boost temperature (buffer and CWU), cheap-hour share, boost command topic and format (`1/0` or setpoint °C).
  - MQTT `optimizer/{buffer,dhw}/boost` (not retained, expiry), `…/boost_target`, `…/strategy`; boost commands only in control mode,
    never retained; valve not commanded in boost mode; shared valve: only one storage boosts at a time.
  - Panel: strategy chip, "Doładuj teraz – 100% do 55 °C" / "Pompa pracuje samodzielnie", boost lane on the timeline.
- **7-day closed-loop simulation** (`optimization/simulation.py`, `scripts/simulate_week.py`, [docs/SIMULATION.md](docs/SIMULATION.md)):
  real week 09–15.10.2026 – heat pump alone 103.73 zł, boost 91.19 zł (−12 %), full control 80.63 zł (−22 %), no hours below minimum.
### Changed
- New installations and existing ones without the option use **boost** – set *Pełne sterowanie* to keep the v0.4 behaviour.

## [0.4.1] – 2026-10-17
Fixes found by analysing a real panel screenshot (buffer at 7 %, 21:00, price 1.239 zł "Drogo", plan: "Grzej teraz").
### Fixed
- **Heat-pump modulation**: the optimiser only knew on/off at full power, so holding the minimum at an expensive hour meant buying a
  full 9 kW hour (overshoot to ~44 °C) and 1-hour bursts every 3–4 h at ~1.05–1.24 zł. New option *Minimalna modulacja pompy ciepła*
  (default 30 %, 100 % = on/off): power levels 30/65/100 %. In the screenshot scenario the 24 h cost drops from 23.73 zł to 17.44 zł.
- **Minimum temperature is now near-hard** (penalty 30 zł/K·h, comfort strategy 100): the plan no longer lets the buffer fall below the
  minimum to wait for a slightly cheaper hour.
- **Truthful recommendation reasons**: "Grzanie konieczne – … spadek poniżej minimum …; cena wysoka – tylko tyle, ile trzeba",
  "Tania energia teraz – ładowanie ciepła na później", "Ładowanie przed droższymi godzinami (od HH:MM)" – instead of always
  "najniższy koszt ciepła w horyzoncie"; includes the modulation level.
- **Fair savings**: compared with an on/off thermostat that keeps the **same minimum** (was: a thermostat holding the target, which
  inflated savings – the old on/off plan was in fact 4.77 zł worse than a simple thermostat).
- Heat-pump efficiency is computed from the **bottom** layer (the water the heat pump heats) when a bottom sensor exists.
- *Aktualna cena całkowita (z dystrybucją)* now applies the current G12/G13 zone.
- Panel: price level ("Tanio/Średnio/Drogo") is computed from the next 24 h (same as *Tania energia teraz*); "Z dystrybucją" says when
  no distribution rate is set; "Grzanie: teraz" when heating now; "Grzej teraz – moc 30%".
### Added
- MQTT `optimizer/buffer/hp_modulation`, `optimizer/dhw/hp_modulation` (recommended heat-pump power %, not retained).

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
