# Loxone integration example (MQTT)

Pstryk AI only **advises**. Loxone keeps full responsibility for safety: hardware thermostats, over-temperature protection, pumps,
mixers and heat sources must work without MQTT.

## 1. Gateway
Use an MQTT gateway for Loxone (e.g. LoxBerry *MQTT Gateway* plugin) connected to the same broker as Home Assistant.
Subscribe to:

| Topic | Loxone virtual input | Type |
|---|---|---|
| `pstryk_ai/home/optimizer/buffer/should_heat` | `VI_PstrykShouldHeat` | digital (1/0) |
| `pstryk_ai/home/optimizer/buffer/mode` | `VTI_PstrykMode` | text (`advisory`/`control`/`fallback`) |
| `pstryk_ai/home/optimizer/buffer/target_temperature` | `VI_PstrykTargetT` | analog °C |
| `pstryk_ai/home/prices/current` | `VI_PstrykPrice` | analog PLN/kWh |
| `pstryk_ai/home/cheap/now` | `VI_PstrykCheap` | digital |
| `pstryk_ai/home/availability` | `VTI_PstrykOnline` | text |

## 2. Freshness watchdog
`should_heat` is republished every hour (non-retained, expires after ~75 min). In Loxone:

* *Monoflop* `MF_Fresh` (on-time 4500 s) triggered by every change/receipt of `VI_PstrykShouldHeat` (use the gateway's "receive" pulse).
* `Valid = MF_Fresh AND (VTI_PstrykMode == "control") AND (VTI_PstrykOnline == "online")`.

## 3. Logic (pseudo-config)

```
LocalDemand   = BufferT < BufferMinLocal                 // local thermostat, always active
Recommendation= Valid AND VI_PstrykShouldHeat
Setpoint      = Valid ? MIN(VI_PstrykTargetT, BufferMaxLocal) : BufferTargetLocal
HeatRequest   = LocalDemand OR (Recommendation AND BufferT < Setpoint)
HeatRequest   = HeatRequest AND NOT OverTempAlarm AND NOT FaultHP   // hard interlocks last
```

* `BufferMaxLocal` must be ≤ the manufacturer limit and independent from MQTT values.
* With `mode = advisory` (default) Loxone only displays the recommendation; switch *Tryb doradczy* off in Home Assistant **after** the
  interlocks above are in place to get `mode = control`.
* `mode = fallback` means: ignore Pstryk AI, use local thermostat.

## 4. Price-based loads
`VI_PstrykCheap` can enable non-critical loads (e.g. DHW boost) with a minimum on-time block in Loxone.
