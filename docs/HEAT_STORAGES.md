# Heat storages, heaters and hot water (CWU)

Every feature below is **off by default** and can be switched on in *Configure* (options) – and most of them also at runtime with a
switch entity. A feature switched off in the options cannot be switched on by its runtime switch.

## 1. Buffer with top and bottom sensors
*Configure → Thermal buffer*

| Option | Meaning |
|---|---|
| Buffer TOP – HA sensor / exact MQTT topic / JSON key | required (migrated from the former single "buffer temperature" option) |
| Buffer BOTTOM – HA sensor / exact MQTT topic / JSON key | optional |
| Heat pump maximum supply temperature | the heat pump cannot heat the storage above this (default 55 °C) |

* Mean temperature = (top + bottom) / 2 drives the energy balance and the charge in % (`Naładowanie bufora`).
* The comfort check uses the **top** layer (mean + half the measured difference), because the top feeds the heating circuits.
* Without a bottom sensor the top temperature is used as before.
* Upgrading from ≤ 0.3: the existing buffer topic/entity/JSON key are moved automatically to the *top* options (config entry 1.1 → 1.2).

### Heat-pump modulation and comfort (v0.4.1)
* *Minimalna modulacja pompy ciepła* (default 30 %): the plan may run the heat pump at 30 / 65 / 100 % power. At expensive hours it
  delivers only the heat needed to hold the minimum and charges the storage when energy is cheap. Set 100 % for an on/off compressor.
* The minimum temperature is treated as a near-hard limit; the comfort strategy makes it stricter.
* The recommended power is published on `optimizer/buffer/hp_modulation` (and `optimizer/dhw/hp_modulation`).
* "Oszczędność" compares with an on/off thermostat that keeps the same minimum (min + 1 K … min + 6 K).

### Heat-pump strategy (v0.5.0)
*Configure → Buffer → Strategia sterowania pompą*, also switchable at runtime with the select **Strategia sterowania pompą**:

| Strategy | Behaviour |
|---|---|
| **Tylko doładowanie** (`boost`, default) | The heat pump keeps its own logic (thermostat / weather curve) and holds its setpoint (*Nastawa własna pompy ciepła*, optionally on a heating curve). Pstryk AI only says *"now run at 100 % up to the boost temperature"* in cheap hours, when that heat is cheaper than what the heat pump would make on its own later (the lower COP at the higher temperature is included). |
| **Pełne sterowanie** (`full`) | Pstryk AI plans every hour (on/off/modulation, heaters, valve) – v0.4 behaviour. |

Boost options:

| Option | Meaning |
|---|---|
| `boost_temperature` | boost up to this temperature (capped by the heat-pump maximum and the buffer maximum), default 55 °C |
| `boost_cheap_share` | boosts only in the cheapest X % of the next 24 h (or at negative prices), default 40 % |
| `boost_command_topic` | optional exact topic of your heat pump/Loxone; control mode only, never retained |
| `boost_command_format` | `1`/`0` or the setpoint in °C (`55.0`, `0` = end of boost) |
| `dhw_boost_temperature`, `dhw_boost_command_topic` | the same for the hot-water tank |

In boost mode the binary sensor *Grzanie bufora zalecane* means "boost now", `optimizer/buffer/boost` = `1`, and the valve topic is
not commanded (the heat pump's own controller switches it). Measured result on a real week: [SIMULATION.md](SIMULATION.md).

### Heat-pump physics (v0.6)
*Configure → Buffer*:

| Option | Meaning |
|---|---|
| *Moc grzewcza pompy przy −15 °C* (`heat_pump_thermal_power_minus15`) | heat output at −15 °C from your datasheet (e.g. 6.5 kW for a 9 kW unit). Empty = typical −1.2 %/K below +7 °C. Used for both storages. |
| *Nachylenie krzywej grzewczej* (`heating_curve_slope`) | 0 = fixed. Otherwise the heat pump's setpoint (*Nastawa własna pompy*) and the minimum apply at 0 °C outdoors and rise by this many K per 1 K of frost (fall in mild weather), e.g. 0.3–0.5 for floor heating. |
| *Minimalna modulacja* | now gives five power steps (e.g. 30/48/65/82/100 %); below it the model counts cycling losses (EN 14825). |

The optimiser also knows that an inverter is more efficient at part load. In *Tylko doładowanie* it chooses the boost temperature
(40–55 °C) per situation; `optimizer/buffer/boost_target` carries the chosen stop temperature for the current hour.
Algorithm and benchmark: [OPTIMIZATION.md](OPTIMIZATION.md), [SIMULATION.md](SIMULATION.md).

## 2. Auxiliary heater (electric or gas)
*Configure → Buffer heater* and *Configure → CWU heater*

| Option | Meaning |
|---|---|
| Use the heater | on/off (runtime switch *Grzałka bufora* / *Grzałka CWU*) |
| Heater type | electric (efficiency ≈ 1.0) or gas boiler (efficiency ≈ 0.92, cost = gas price per kWh of fuel) |
| Power steps | heat output stages in kW, e.g. `2,4,6` |
| Maximum temperature | optional, may be higher than the heat-pump limit (legionella) |
| Command topic + format | exact topic for Loxone; `1/0` or power in kW; **only published when advisory mode is off** |
| State topic + JSON key | optional measured state/power of the heater (energy and cost tracking) |

Each hour the optimiser chooses heat pump, heater stage, both or nothing by the cost of *delivered heat*:
heat pump `price / COP`, electric `price / efficiency`, gas `gas price / efficiency`. Typical results: the element runs at
negative/very low prices, in hard frost when the COP collapses, or to reach temperatures above the heat-pump limit.

## 3. Hot-water tank (CWU)
*Configure → Hot water (CWU)*

| Option | Meaning |
|---|---|
| Top / bottom sensors | like the buffer |
| Volume, min/max/target | tank parameters |
| Ready times + required temperature | e.g. `06:00,19:00` at ≥ 45 °C – the plan guarantees the top layer at these times |
| Hot-water use per day | litres at 45 °C, distributed with a typical daily profile (or the learned profile) |
| Heat pump for CWU | `valve` – one heat pump with a switching valve serves the buffer *or* CWU each hour; `none` – CWU is heated only by its heater |
| CWU priority | CWU is planned first; the buffer gets the remaining heat-pump hours |
| Valve command topic | optional; payload `buffer` / `dhw` / `idle`; only in control mode |
| Legionella cycle | reach the legionella temperature (default 60 °C) every N days (default 7), at the cheapest time before the deadline; the heater is used above the heat-pump limit |

Planning ("priority-sequential MPC"): the priority storage is optimised first with the heat pump available every hour; the other storage is
then optimised with the heat pump only in the remaining hours and with the electric power left under the connection limit.

## 4. Connection power limit
*Configure → Power limit and metering*: limit in kW, typical base load, optional heat-pump power reading (entity or MQTT, W or kW).
The heat pump + heaters of both storages + device schedules never exceed the limit in the plan.

## 5. Measured consumption
With a heat-pump power reading (and heater state topics) the integration integrates energy every update and values it at the current
price: *Zużycie/Koszt pompy ciepła dziś*, *Zużycie grzałek dziś* (+ month totals in attributes).

## 6. Learning (optional)
*Configure → Learning*
* **Heat demand and losses**: from hours without heating (needs a power reading, otherwise the plan is used to detect idle hours),
  fits building demand per K and standby losses (non-negative least squares).
* **Hot-water profile**: average draw per hour of day from CWU temperature drops.
* **COP**: measured/model COP ratio in heat-pump hours (needs power metering).
* **Use learned values**: applied only after enough samples (≥ 36 hours, COP ≥ 12) and plausibility checks. Results: *Uczenie parametrów*.

## 7. Safety
* Advisory mode is the default: recommendations only, no commands to your topics.
* Commands (heaters, valve) are never retained; a missing/stale temperature puts that storage in `fallback` → heaters `0`, valve `idle`.
* Hardware thermostats, safety temperature limiters and manufacturer limits must stay in Loxone / the devices.
