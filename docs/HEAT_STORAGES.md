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
