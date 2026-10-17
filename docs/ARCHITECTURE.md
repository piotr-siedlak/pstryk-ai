# Architecture

```text
                 ┌──────────────── Home Assistant (custom integration pstryk_ai) ────────────────┐
                 │                                                                               │
  Pstryk API ───►│ api/pstryk.py ──┐   (budget 2 req/h per key, 429 → Retry-After block)         │
  ENTSO-E ──────►│ api/entsoe.py ──┤                                                             │
  PSE API v2 ───►│ api/pse.py ─────┼──► storage/history.py (HA Store JSON, retention)           │
  TGE (opt-in) ─►│ api/tge.py ─────┤        storage/cache.py (last good payloads, budget state)  │
  Open-Meteo ───►│ api/weather.py ─┘                                                             │
                 │          │                                                                    │
                 │          ▼                                                                    │
                 │  forecasting/  features → baseline (A) + ridge per horizon (B) → ensemble (C) │
                 │                backtesting (rolling origin) → weights, intervals, metrics     │
                 │          │  market price forecast PLN/MWh, P10/P50/P90, confidence           │
                 │          ▼                                                                    │
                 │  tariff.py → timeline.py  ACTUAL_PSTRYK > PUBLISHED_TGE > MODEL > FALLBACK   │
                 │          │                                                                    │
                 │          ▼                                                                    │
                 │  optimization/ cheapest_hours · scheduler (DP) · heat_pump (COP) ·            │
                 │                thermal_storage (DP/MPC)                                       │
                 │          │                                                                    │
                 │          ▼                                                                    │
                 │  outputs.py ──► sensors / binary sensors / controls (Polish names)           │
                 │             └─► mqtt/ schemas + publisher (HA MQTT broker) + discovery       │
                 └───────────────────────────────────────────────────────────────────────────────┘
```

## Layers

| Layer | Modules | Notes |
|---|---|---|
| Providers | `api/*` | Pure Python + aiohttp, no HA imports, independent health status per provider. |
| Models | `models/*` | Dataclasses; every price slot carries `source` and `quality`. All datetimes aware UTC. |
| Storage | `storage/*` | HA `Store` with versioned migration hook; delayed writes; retention on save. |
| Forecasting | `forecasting/*` | Pure Python; CPU-bound parts run in the executor. |
| Optimisation | `optimization/*` | Pure Python dynamic programming; deterministic. |
| Orchestration | `coordinator.py` | `DataUpdateCoordinator` without polling interval; event-aware schedule. |
| Presentation | `sensor.py` …, `mqtt/*` | Time series as attributes (excluded from recorder) or JSON MQTT topics. |
| Panel | `panel.py`, `frontend/pstryk-ai-panel.js` | Sidebar page; dependency-free web component reading the entity states (no extra API calls). |

## Scheduler (local time Europe/Warsaw)

| Time | Action | External calls |
|---|---|---|
| every hour :00:05 | slot boundary: rebuild timeline, sensors, MQTT | none |
| every hour :02 | Pstryk combined request (meter, cost, pricing if needed) | 1 Pstryk |
| :32 between 13:00–17:59 | retry tomorrow's Pstryk prices until confirmed | ≤ 1 Pstryk |
| 00:05 | rollover, market validation, forecast | ENTSO-E/TGE/PSE |
| 03:10 / 09:10 / 15:10 / 21:10 (refresh 6 h) + 06:00 + 18:00 | weather + PSE plan + forecast | Open-Meteo, PSE |
| 10:45 | TGE Fixing I check, forecast | ENTSO-E/TGE |
| 13:00 | **main daily calculation** + forecast snapshot | ENTSO-E/TGE/PSE |
| 14:05 | Fixing II / late publication | ENTSO-E/TGE |
| 01:17, 07:17, 11:17, 19:17, 22:17 | Pstryk daily/monthly balance (skipped while waiting for tomorrow's prices) | 1 Pstryk |
| 03:30 | weekly retraining check | none |

13:00 is never treated as a guarantee: confirmation happens only when a full, non-placeholder day arrives from Pstryk. When it does,
the integration fires `pstryk_ai_prices_confirmed`, stores a forecast snapshot, recomputes windows/schedules and republishes MQTT.

## Data integrity rules
* Confirmed Pstryk prices are merged, never overwritten by forecasts, and restored from cache after restart/outage.
* Published market prices are shown as `PUBLISHED_TGE` (tariff applied) – only from ENTSO-E or TGE, never from RCE.
* Forecast slots always carry P10/P50/P90 and `confidence`.
* No secrets in logs, diagnostics (redacted) or MQTT.
