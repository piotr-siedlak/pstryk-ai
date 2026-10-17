# Research report (Phase 1)

Research date: 2026-10-16. Repositories were cloned and their **source code** inspected (not only READMEs).

## 1. Existing projects

| Project | License | What it does | Reused (idea, not code) |
|---|---|---|---|
| [kubass4/Pstryk-all-in-one](https://github.com/kubass4/Pstryk-all-in-one) | MIT | Prices, usage, cost, balances. Uses the **deprecated** `energy-usage` / `energy-cost` endpoints. | Sensor catalogue (daily/monthly balance, sold value). |
| [balgerion/ha_Pstryk](https://github.com/balgerion/ha_Pstryk) | MIT | `unified-metrics?metrics=pricing`, buy/sell price, cheap/expensive flags, EVCC-style MQTT price arrays, file cache. | Field names `price_gross`, `price_prosumer_gross`, `is_cheap`, `is_expensive`; the **placeholder detection** idea (tomorrow returns constant values before publication); EVCC payload shape. |
| [Bankilo/pstryk-home-assistant](https://github.com/Bankilo/pstryk-home-assistant) | MIT | Hourly prices, cheap/expensive hours. | Confirms field usage. |
| [szczepuz999/tge_rdn_integration](https://github.com/szczepuz999/tge_rdn_integration) | none found | Scrapes the TGE RDN HTML table with BeautifulSoup, tariff zones, Polish holidays. | Table layout (`YYYY-MM-DD_Hnn`, `_Q` rows, `dateShow` = delivery − 1). **No code copied** (no license). |
| [PiotrMachowski/…-TGE](https://github.com/PiotrMachowski/Home-Assistant-custom-components-TGE) | MIT | TGE RDN scraping. | Confirms the TGE page as the only public TGE source. |
| [JaccoR/hass-entso-e](https://github.com/JaccoR/hass-entso-e) | Apache-2.0 | ENTSO-E A44 parsing incl. PT15M/PT60M, duplicate periods. | Parsing approach (resolution handling, A03 curve fill). Re-implemented. |
| [BackupBaTTerY/energypriceforecast-home-assistant](https://github.com/BackupBaTTerY/energypriceforecast-home-assistant) | MIT | Forecast vs. actual separation, accuracy tracking, cheapest windows. Service horizon 48 h free / 120 h paid. | Idea of measuring *optimization* regret, not only price error. Not usable for 168 h. |
| [jyourstone/power_saver](https://github.com/jyourstone/power_saver) | MIT | Cheapest-hour scheduling, min runtime, fewer switches. | Requirements for device profiles. |
| [EMHASS](https://emhass.readthedocs.io/) | MIT | LP/MILP optimisation incl. thermal loads. | Thermal model framing (MPC, receding horizon). Not embedded (heavy dependencies). |

## 2. APIs (verified live)

### Pstryk – `https://api.pstryk.pl/integrations/`
* OpenAPI schema: `GET /integrations/schema/` (the Swagger UI is at `/integrations/swagger/`). The only documented path is
  `GET /integrations/meter-data/unified-metrics/`.
* Auth: header `Authorization: <api key>` (no `Bearer`).
* Parameters: `metrics` (required: `meter_values,cost,carbon,pricing`), `resolution` (required: `minute|hour|day|month`),
  `window_start` (required, UTC), `window_end`, `for_tz` (**not allowed** with `hour`/`minute`), `breakdown` (`none|device`), `temporal` (`range|latest`).
* Frame semantics: `start`, `end`, optional `is_live`, `metrics.{meterValues|cost|pricing}`; `summary` with totals.
* Documented cost fields: `energy_import_cost`, `var_dist_cost_net`, `fix_dist_cost_net`, `energy_cost_net`, `service_cost_net`,
  `power_fee_cost_net`, `vat`, `var_dist_cost_vat`, `fix_dist_cost_vat`, `energy_sold_value(_net)` with
  `energy_sold_value = export_kwh · max(tge_price, 0) · (1 + vat_rate)`.
* Pricing fields observed in community implementations: `price_gross`, `price_net`, `price_prosumer_gross`, `is_cheap`, `is_expensive`.
  They are **not described in the schema**; the parser treats every field as optional and records which were seen (diagnostics).
* Terms (<https://pstryk.pl/regulamin-api>): private non-commercial use; **3 requests/hour** for “heavy” endpoints, HTTP 429 above;
  no scraping/dumping, no mass caching, no derivative models/benchmarks/competing tools, no sharing results with third parties, keys must not be published.

### PSE API v2 – `https://api.raporty.pse.pl/api/<entity>`
* No auth. OData-like: `$filter=business_date ge 'YYYY-MM-DD' and business_date le '…'`, paging via `nextLink` (100 rows/page).
* `pk5l-wp` (coordinated plan, **≈7 days ahead**, hourly): `grid_demand_fcst`, `fcst_wi_tot_gen`, `fcst_pv_tot_gen`, `planned_exchange`,
  `plan_dtime_utc` = end of the hour, `publication_ts_utc`.
* `kse-load` (15 min): `load_fcst`, `load_actual`.  `his-wlk-cal` (15 min realised): `demand`, `wi`, `pv`, `jg*`, `swm_*`.
* `rce-pln` (15 min): `rce_pln`. **RCE is not the TGE RDN price** – kept as a separate dataset and only used as a labelled proxy.

### ENTSO-E – `https://web-api.tp.entsoe.eu/api`
* Free security token. `documentType=A44`, `in_Domain=out_Domain=10YPL-AREA-----S`, `periodStart/periodEnd=yyyyMMddHHmm` (UTC), ≤ 1 year/request.
* Resolutions PT60M and PT15M (post-2025 15-minute market), curve type A03 omits repeated points.

### TGE
* No public API. `https://tge.pl/energia-elektryczna-rdn?dateShow=DD-MM-YYYY` shows contracts for the **next** day.
* Rows `YYYY-MM-DD_Hnn` (hourly, `H02a` on DST end) and `YYYY-MM-DD_Qhh:mm` (quarter, label = end of quarter); columns: duration,
  Fixing I PLN/MWh, volume, continuous, Fixing II EUR/PLN, …
* Fixing I results ≈10:30, Fixing II ≈13:50; from 2026-06-10 hourly Fixing I prices derive from 15-minute products.
* The site resets plain HTTP clients at times (bot protection). Treated as **opt-in, experimental**, ≤ 2 requests per publication.

### Open-Meteo
* Forecast `api.open-meteo.com/v1/forecast` (multi-location with comma lists, multi-model suffixes `var_model`),
  historical forecasts `historical-forecast-api.open-meteo.com`, previous runs `previous-runs-api.open-meteo.com`
  (`var_previous_dayN`), archive `archive-api.open-meteo.com`. Variables incl. `wind_speed_80m/100m/120m`.
* Free for non-commercial use.

## 3. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Pstryk 3 req/h limit, shared across integrations | Local sliding-window budget of 2 req/h **per key, persisted across restarts**; 429 blocks for `Retry-After`; one combined request (`meter_values,cost,pricing`) per hour; no retries that would spend budget. |
| Undocumented Pstryk pricing fields change | Tolerant parser, field-presence diagnostics, placeholder detection, cached last-good payload. |
| Pstryk ToS: no derivative models | Model trained **only** on public market data (ENTSO-E/TGE/PSE RCE). Pstryk prices used live, plus a 14-day local comparison; tariff calibration is opt-in. |
| TGE scraping restrictions/bot protection | Opt-in only, minimal requests, ENTSO-E recommended. |
| RCE confused with RDN | Separate provider key `pse_rce`; never shown as `PUBLISHED_TGE`; labelled `pse_rce_proxy` when used for training. |
| 15-minute vs hourly | Native points stored; hourly means only from 4 complete quarters; hourly products take precedence. |
| DST 23/25-hour days | All internal times UTC; local-day bounds via `zoneinfo`; tests for both transitions. |
| Look-ahead bias in backtests | Horizon-day feature construction, expanding-window refits, out-of-sample intervals; archived-forecast optimism documented. |
| Heavy ML in HA | Pure-Python ridge (no dependencies); optional external service left for later. |
| Unsafe heating control | Advisory by default, non-retained expiring commands, explicit mode topic, fallback when stale. |

## 4. Implemented from scratch
Unified price timeline with precedence, horizon-specific models, rolling-origin backtesting with optimisation metrics, uncertainty-aware window
search, DP device scheduler, DP/MPC thermal buffer optimiser with COP(T_out, T_supply), MQTT schema, Polish UI.
