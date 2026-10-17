# MQTT topics

Publication uses the broker configured in Home Assistant's MQTT integration. Prefix (default) `pstryk_ai/home`.

* **Scalar topics** carry a plain value (`0.61234`, `1`/`0`, ISO 8601 timestamps).
* **JSON topics** use the envelope `{"schema":"pstryk_ai/v1","type":…,"generated_at":…,"valid_until":…,"unit":…,"data":…}`.
* Records: `start, end, value, unit, source, quality, generated_at, valid_until` (+ `p10, p50, p90, confidence, model` for forecasts).
* `source` ∈ `ACTUAL_PSTRYK | PUBLISHED_TGE | MODEL_FORECAST | FALLBACK_FORECAST | UNAVAILABLE`; `quality` ∈ `confirmed | estimated | forecast | unknown`.
* QoS configurable (default 1). Data topics retained (configurable) **with `valid_until`**.
* `optimizer/buffer/should_heat` is **never retained** and carries an MQTT v5 message expiry (≈75 min).

| Topic | Type | Retained | Content |
|---|---|---|---|
| `prices/current` | scalar | yes | current buy price PLN/kWh |
| `prices/current/json` | JSON | yes | current slot record |
| `prices/next` | scalar | yes | next hour price |
| `prices/today`, `prices/tomorrow` | JSON list | yes | local-day records |
| `prices/pstryk/buy`, `prices/pstryk/sell` | JSON list | yes | confirmed Pstryk prices only |
| `prices/tge` | JSON list | yes | published market price (tariff applied) + `market_pln_mwh` |
| `prices/forecast/7d` | JSON columnar | yes | 168 h: `start[]`, `value[]`, `p10[]`, `p90[]`, `source[]`, `confidence[]` |
| `prices/forecast/day/1` … `/7` | JSON list | yes | local day today+N |
| `cheap/now` | scalar 1/0 | yes | relative (lowest quartile of next 24 h) or below absolute threshold |
| `cheap/next_start` | scalar ISO | yes | start of best 3 h window in 24 h |
| `cheap/best_2h`, `best_4h`, `best_6h`, `best_24h` | JSON | yes | windows (`best_24h` = cheapest N hours in 24 h) |
| `cheap/schedule` | JSON | yes | all windows + device schedules |
| `weather/current`, `weather/forecast`, `weather/temperature` | JSON/scalar | yes | local weather |
| `weather/wind`, `weather/solar` | JSON | yes | national wind/solar indices |
| `optimizer/buffer/should_heat` | scalar 1/0 | **no**, expiry | recommendation |
| `optimizer/buffer/mode` | scalar | yes | `advisory` / `control` / `fallback` |
| `optimizer/buffer/target_temperature` | scalar °C | yes | |
| `optimizer/buffer/next_start`, `next_stop` | scalar ISO | yes | first heating block |
| `optimizer/buffer/expected_cost` | scalar PLN | yes | next 24 h |
| `optimizer/buffer/schedule` | JSON | yes | full plan incl. per-hour steps |
| `status` | JSON | yes | providers, flags |
| `availability` | `online`/`offline` | yes | `offline` on unload |
| `forecast/status`, `forecast/confidence`, `forecast/last_update` | JSON/scalar | yes | model info |
| `api/pstryk/status`, `api/tge/status`, `api/entsoe/status`, `api/pse/status`, `api/weather/status` | scalar | yes | `ok`, `error`, `rate_limited`, … |
| `evcc/prices` (optional) | JSON list | yes | `[{"start","end","value"}]` (EVCC custom forecast tariff) |

## Renaming or disabling topics
*Settings → Devices & services → Pstryk AI → Configure → MQTT topics* lists all 46 topics. Each field is the topic name **relative to
the prefix**:

| Field value | Published to |
|---|---|
| `prices/current` (default) | `pstryk_ai/home/prices/current` |
| `cena/teraz` | `pstryk_ai/home/cena/teraz` |
| `/loxone/energia/cena` (leading `/`) | `loxone/energia/cena` (absolute) |
| *(empty)* | not published |

Wildcards (`#`, `+`) and empty levels are rejected, and two topics may not resolve to the same name. After a change the integration
removes retained messages from topics it no longer publishes, so subscribers do not keep reading stale data. MQTT discovery follows the
renamed topics; the JSON payload schema does not change.

## Example payloads

`pstryk_ai/home/prices/today`
```json
{"schema":"pstryk_ai/v1","type":"prices_today","generated_at":"2026-10-16T11:00:05Z","valid_until":"2026-10-16T17:00:05Z","unit":"PLN/kWh",
 "data":[{"start":"2026-10-15T22:00:00Z","end":"2026-10-15T23:00:00Z","value":0.61234,"unit":"PLN/kWh","source":"ACTUAL_PSTRYK",
          "quality":"confirmed","generated_at":"2026-10-16T11:02:00Z","valid_until":null,"is_cheap":false,"is_expensive":false}]}
```

`pstryk_ai/home/prices/forecast/day/3` (forecast record)
```json
{"start":"2026-10-18T16:00:00Z","end":"2026-10-18T17:00:00Z","value":0.88412,"unit":"PLN/kWh","source":"MODEL_FORECAST","quality":"forecast",
 "generated_at":"2026-10-16T11:00:00Z","valid_until":"2026-10-16T17:00:05Z","p10":0.71,"p50":0.88412,"p90":1.05,"confidence":0.512,"model":"ensemble"}
```

`pstryk_ai/home/optimizer/buffer/schedule` (abridged)
```json
{"schema":"pstryk_ai/v1","type":"buffer_plan","generated_at":"2026-10-16T11:00:05Z","valid_until":"2026-10-16T12:15:05Z",
 "data":{"should_heat":false,"target_temperature":48.5,"recommended_start":"2026-10-16T12:00:00Z","recommended_stop":"2026-10-16T14:00:00Z",
  "recommended_duration":2.0,"expected_energy_kwh":11.2,"expected_cost_pln":6.31,"expected_savings_pln":1.84,"mode":"advisory",
  "optimization_confidence":0.93,"optimization_reason":"Czekaj – tańsze ciepło od 2026-10-16T12:00:00Z",
  "schedule":[{"start":"2026-10-16T11:00:00Z","heat":0,"t_start":41.0,"t_end":38.3,"electric_kwh":0,"thermal_kwh":0,"price":0.83,"cop":3.1,"cost":0,"source":"ACTUAL_PSTRYK"}]}}
```

## Discovery
With *MQTT discovery* enabled, only a handful of key values are announced (`homeassistant/<component>/pstryk_ai_<id>/<key>/config`).
Time series are never turned into hundreds of entities.

## Consumers
* **Loxone**: subscribe to scalar topics via MQTT gateway (e.g. Loxberry MQTT Gateway); see `examples/loxone.md`.
* **Node-RED / ioBroker**: JSON topics with `valid_until` – discard data with `valid_until < now`.
* **EVCC**: `tariffs: grid: type: custom, forecast: {source: mqtt, topic: pstryk_ai/home/evcc/prices}` (check your EVCC version's syntax).
