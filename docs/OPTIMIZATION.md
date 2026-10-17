# Optimization

## Cheapest / most expensive periods (`optimization/cheapest_hours.py`)
* Works on the **whole timeline** (today, tomorrow, forecast days); windows may cross midnight and span days.
* Contiguous windows of 1, 2, 3, 4, 6, 8 h (overall and within 24 h), cheapest *N* non-consecutive hours, most expensive 1 h / 3 h.
* Relative thresholds: lowest/highest quartile of the next 24 h; absolute threshold configurable (`Próg ceny`).
* **Uncertainty-aware**: forecast slots are scored with `p50 + risk · (p90 − p50)` (`risk_aversion`, default 0.3).
  A window beyond `max_speculative_hours` (default 72 h) wins only if it beats the best near-term window by more than its average
  half-interval `(p90 − p10)/2`. This prevents postponing work on speculative savings.
* Published Pstryk prices always take precedence (they are the timeline values). If no future prices exist, only available slots are used.

## Device profiles (`optimization/scheduler.py`)
JSON list in the options (`Optymalizacja → Profile urządzeń`):

```json
[
  {"name": "Pralka", "power_kw": 2.0, "duration_h": 2, "consecutive": true, "allowed_start": "06:00", "allowed_end": "22:00"},
  {"name": "Bojler", "power_kw": 3.0, "required_energy_kwh": 6, "efficiency": 0.98, "min_run_h": 1, "max_price": 0.9},
  {"name": "EV", "power_kw": 7.4, "duration_h": 4, "deadline": "2026-10-17T05:00:00Z", "priority": 1, "min_run_h": 2, "min_off_h": 1}
]
```

Devices with a measured value (DHW tank, EV) can read it from MQTT and skip work when the target is already reached:

```json
[
  {"name": "Bojler CWU", "power_kw": 3.0, "duration_h": 2, "target": 55, "temperature_topic": "loxone/cwu/temperatura"},
  {"name": "EV", "power_kw": 7.4, "duration_h": 4, "target": 80, "value_topic": "evcc/loadpoints/1/vehicleSoc"},
  {"name": "Bufor CO", "power_kw": 3.0, "duration_h": 3, "target": 45, "temperature_topic": "loxone/bufor", "temperature_key": "value"}
]
```

When the current value is ≥ `target` the profile gets no hours (reason *Cel osiągnięty*); when the reading is missing or stale the
schedule is planned normally and the reason says so.

Fields: `name, power_kw, duration_h | required_energy_kwh (+efficiency), min_run_h, min_off_h, allowed_start/allowed_end (local, may cross
midnight), earliest_start, deadline (default now + 24 h), priority, max_price, target, temperature_topic (alias value_topic), temperature_key (alias value_key), enabled, consecutive`.

Non-consecutive profiles are solved by dynamic programming over hourly slots with state *(hours done, on/off, run/off length)*, which
enforces minimum run and off times exactly. When no prices are available the fallback schedules the earliest allowed hours so the task still
completes (reason: *harmonogram awaryjny*). Each profile has a sensor `Harmonogram: <name>` (next start + full plan in attributes).

## Thermal buffer (`optimization/thermal_storage.py`, `heat_pump.py`)

Energy balance per hour:

```
C·ΔT = Q_hp − Q_demand(T_out) − U_loss·(T_buffer − 20 °C)
C    = volume_l · 0.001163 kWh/(l·K)          (≈ 0.58 kWh/K for 500 l)
Q_demand = building_heat_loss_kw_per_k · max(0, T_base − T_out)
Electricity = Q_hp / COP(T_out, T_supply ≈ T_buffer + 5 K)
```

COP: either nominal COP (A7/W35) with a Carnot-ratio dependency, or a measured curve `-15:2.0,-7:2.6,2:3.3,7:4.1` (W35) corrected for
supply temperature. A hotter buffer **lowers COP** – the optimiser compares the cost of *delivered heat*, not of electricity.

The **current buffer temperature** comes from the MQTT topic `buffer_temperature_topic` (preferred) or the Home Assistant sensor; the
outdoor temperature for the current hour likewise (`outdoor_temperature_topic`), later hours use the Open-Meteo forecast.

Optimisation: dynamic programming over a 0.5 K grid (exact temperature carried along the cheapest path) and compressor state, horizon up
to 72 h (receding horizon – recomputed every hour and whenever inputs change). Objective = cost (risk-adjusted for forecasts) + comfort
penalty below `min` (5 PLN/K·h *min_cost*, 20 PLN/K·h *comfort*) + start penalty − value of heat left at the end. Constraints: max
temperature (heating is truncated at the limit), min runtime, min off time; starts above `maximum_start_count` are reported.

Savings are computed against a non-optimised hysteresis thermostat (target −2 K … target) on the same prices and weather, corrected for
the different heat content at the end of the horizon.

Outputs: `should_heat, target_temperature, recommended_start/stop/duration, expected_energy_kwh, expected_cost_pln, expected_savings_pln,
next_heating_window, thermal_energy_target_kwh, optimization_confidence, optimization_reason` (+ hourly `schedule`).

### Safety
* **Advisory by default** (`Tryb doradczy` on, `optimizer/buffer/mode = advisory`).
* No direct device control. Loxone (or another controller) decides, and its local thermostat, over-temperature protection, pumps and
  mixers stay independent of MQTT.
* `should_heat` is not retained and expires; `valid_until` on every plan.
* Missing buffer sensor, unavailable current price or stale data → `mode = fallback`, `should_heat = 0` with the reason
  *sterowanie lokalne*. The fallback means "use your local thermostat", never "heat".
