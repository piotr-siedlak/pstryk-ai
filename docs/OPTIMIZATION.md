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

## Heating: thermal storage optimiser (`optimization/thermal_storage.py`, `boost.py`, `heat_pump.py`)

### Model (v0.6)
Energy balance per hour (buffer or hot-water tank):

```
C·ΔT = Q_hp + Q_heater − Q_demand(T_out) − U_loss·(T − 20 °C)
C        = volume_l · 0.001163 kWh/(l·K)                  (≈ 0.58 kWh/K for 500 l)
Q_demand = building_kw_per_k · max(0, T_base − T_out)      (or the hot-water draw profile)
E_hp     = Q_hp / COP
```

Heat-pump physics – each item changes real decisions, see the benchmark below:

| Effect | Model | Why it matters |
|---|---|---|
| COP vs temperatures | Carnot ratio from nominal COP (A7/W35) or a measured W35 curve; supply = **bottom layer** + condenser lift | a hotter tank lowers COP – "charge more, earlier" is not automatically cheaper |
| **Part load** (inverter) | condenser lift = 5 K × power fraction | 30 % power has a ~5–10 % better COP than 100 % |
| **Cycling** below minimum modulation | EN 14825: COP × CR / (0.9·CR + 0.1) | an on/off compressor (or an inverter below its minimum) wastes energy on short runs |
| **Output in frost** | heat output at −15 °C from the options, else −1.2 %/K below +7 °C | a 9 kW unit gives ~6.6 kW at −15 °C – the plan must pre-charge earlier |
| **Heating curve** (optional) | setpoint and minimum + slope · (0 °C − T_out) | the house needs a hotter buffer in frost and a cooler one in mild weather |

Modulation levels: five evenly spaced steps from the minimum modulation to 100 % (e.g. 30/48/65/82/100 %); finer steps gained < 1 %.

### Strategy *Pełne sterowanie* (full control)
Model-predictive control with dynamic programming: state = mean temperature on a 0.5 K grid (exact temperature carried along the
cheapest path) + compressor run/off counters (+ legionella flag); actions = heat-pump level × heater stage; horizon = all known prices
(today, and tomorrow after the Pstryk publication ≈ 13:00), extended with the price forecast up to 72 h. Objective = electricity/gas cost
+ comfort penalty below the (weather-dependent) minimum (30 zł/K·h, *Komfort* 100) + ready-by penalties + start penalty − value of heat
left at the end. Re-planned every hour and whenever a temperature input changes; only the current hour is executed.

### Strategy *Tylko doładowanie* (boost only, default)
The heat pump keeps its own control. The DP decides in which **cheap hours** (cheapest 40 % of the next 24 h, or negative prices) to run
it at 100 % and **up to which temperature**: the configured boost temperature or one of up to three lower ones (5 K apart). A deep dip or a
negative price justifies 55 °C; a moderate one only 45–50 °C (the extra COP loss would eat the gain); a 30 % spread is not used at all.
The heat pump's own behaviour (hold its weather-compensated setpoint, at reduced output in frost, cycling at low load) is part of the
model, so a boost is recommended only when it really displaces more expensive heat.

### How good is it? (`scripts/benchmark_heating.py`)
Closed loop on three real 4-week periods (winter, spring, autumn 2026), compared with the **perfect-foresight optimum** – one plan over
the whole month with every price known in advance, which no real controller can beat:

| Period | Heat pump alone | Boost only | Full control | Optimum (bound) | Full-control regret |
|---|---:|---:|---:|---:|---:|
| Winter (avg −7.8 °C) | 1434.36 zł | 1398.29 zł (−2.5 %) | 1293.20 zł (−9.8 %) | 1292.43 zł | 0.1 % |
| Spring (negative prices) | 305.03 zł | 242.47 zł (−20.5 %) | 207.89 zł (−31.8 %) | 207.00 zł | 0.4 % |
| Autumn | 183.51 zł | 121.52 zł (−33.8 %) | 97.63 zł (−46.8 %) | 97.90 zł | ≈ 0 % |

The receding-horizon DP with day-ahead prices is within **0.1–0.4 % of the optimum**: a longer horizon, better price forecasts or a
heavier solver cannot save more money with this model. What still matters is the model being right – hence the v0.6 physics.
Details, old-vs-new comparison and caveats: [SIMULATION.md](SIMULATION.md).

### Savings shown in the panel
*Pełne sterowanie*: against a thermostat that keeps the **same weather-dependent minimum** (min + 1 K … min + 6 K) and modulates like an
inverter would; *Tylko doładowanie*: against the heat pump alone. Both are corrected for the different heat content at the end.

Outputs: `should_heat, target_temperature, hp_modulation_pct, boost_target_t, recommended_start/stop/duration, expected_energy_kwh,
expected_cost_pln, expected_savings_pln, next_heating_window, optimization_reason` (+ hourly `schedule`).

### Safety
* **Advisory by default** (`Tryb doradczy` on, `optimizer/buffer/mode = advisory`).
* No direct device control. Loxone (or another controller) decides, and its local thermostat, over-temperature protection, pumps and
  mixers stay independent of MQTT.
* `should_heat` is not retained and expires; `valid_until` on every plan.
* Missing buffer sensor, unavailable current price or stale data → `mode = fallback`, `should_heat = 0` with the reason
  *sterowanie lokalne*. The fallback means "use your local thermostat", never "heat".
