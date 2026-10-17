# 7-day simulation: heat-pump strategies

`scripts/simulate_week.py` replays a real week **hour by hour, as it would run live** (closed loop, model-predictive control):

* every hour the controller sees only the prices known at that time – today, plus tomorrow from 13:00 (Pstryk publication),
* it plans, applies the decision for the current hour, and the "real" buffer moves on with the measured outdoor temperature,
* the next hour starts from the resulting temperature (errors and re-planning are included, nothing is known in hindsight).

Run it yourself (public data, no API key needed):

```bash
python scripts/simulate_week.py --lat 52.03 --lon 21.05
```

Engine: `custom_components/pstryk_ai/optimization/simulation.py` (also covered by `tests/test_v050_boost.py` on synthetic weeks).

## Strategies compared

| Strategy | Who decides | What Pstryk AI sends |
|---|---|---|
| `auto` (reference) | heat pump alone holds its setpoint (`Domyślna temperatura docelowa`) | nothing |
| **`boost`** (*Tylko doładowanie*, default) | heat pump decides when and how; Pstryk AI only adds **100 % boosts in cheap hours** up to the boost temperature | `optimizer/buffer/boost` = 1/0 (+ optional command topic) |
| `full` (*Pełne sterowanie*) | Pstryk AI decides every hour, incl. modulation 30/65/100 % | `should_heat`, `hp_modulation`, target |

## Result – real data, 09–15.10.2026 (168 h)

Data: PSE RCE (public) converted to a customer price with the default tariff – a stand-in for Pstryk prices, which cannot be fetched
without a key – price 0.01 / 0.76 / 1.87 zł/kWh (min/avg/max); Open-Meteo outdoor temperature −0.2 … 14.4 °C (avg 8.8 °C).
Model: 500 L buffer, setpoint 35 °C, min 30 °C, heat pump 9 kW_th / 3 kW_el, COP 3.0 (A7/W35), building 0.25 kW/K, boost to 55 °C,
candidate hours = cheapest 40 % of the next 24 h.

| Strategy | Cost | Saving vs heat pump alone | Electricity | Cost of heat | Hours below min | Compressor starts | Boost hours |
|---|---:|---:|---:|---:|---:|---:|---:|
| auto (heat pump alone) | 103.73 zł | – | 126.7 kWh | 0.296 zł/kWh | 0 | 1 | – |
| **boost (default)** | **91.19 zł** | **12.54 zł (12 %)** | 140.9 kWh | 0.258 zł/kWh | **0** | 13 | 23 |
| full control | 80.63 zł* | 23.10 zł (22 %) | 130.9 kWh | 0.229 zł/kWh | 0 | 22 | – |

\* corrected for a slightly different buffer temperature at the end of the week.

Per day (zł):

| Day | auto | boost | full | boost hours (local) |
|---|---:|---:|---:|---|
| Fri 09.10 | 7.11 | 4.12 | 3.04 | 04, 12–15 (0.01–0.37 zł) |
| Sat 10.10 | 6.25 | 4.91 | 4.69 | 04, 12–13 |
| Sun 11.10 | 8.84 | 6.53 | 5.51 | 13–14 |
| Mon 12.10 | 21.79 | 19.81 | 17.30 | 13–15 |
| Tue 13.10 | 21.60 | 21.34 | 17.92 | 03–04, 12 |
| Wed 14.10 | 17.00 | 15.96 | 14.76 | 04–05, 16 |
| Thu 15.10 | 21.14 | 18.52 | 16.83 | 05, 12–14 |

Sensitivity of `boost` (same week):

| Boost temperature | cheapest 25 % | cheapest 40 % |
|---|---:|---:|
| 45 °C | 5.65 zł | 6.80 zł |
| 50 °C | 8.76 zł | 10.21 zł |
| 55 °C | 10.83 zł | **12.54 zł** |

## Reading the result
* **Boost keeps the heat pump in charge.** Comfort never depends on Pstryk AI: without a boost the heat pump does exactly what it
  does today. Zero hours below the minimum in every run.
* Boosts are used only where they pay off. A boost runs at a higher water temperature (lower COP), so it is worth it only when the
  price spread is larger than the COP loss. With a 30 % spread (e.g. 0.77 vs 1.10 zł) **no boost** is planned – the reason says
  *"doładowanie się nie opłaca w horyzoncie"*; with midday dips or negative prices the buffer is charged to 55 °C.
* Electricity use goes **up** (+11 %) while cost goes **down** – the heat is bought when it is cheap and stored.
* Full control saves more (it can also *lower* the heat pump's work at expensive hours and modulate) but takes over the decisions
  and starts the compressor more often. Choose it with the select *Strategia sterowania pompą* if you want it.
* Caveats: one week, one building model, RCE-based prices instead of real Pstryk prices, perfect heat-pump behaviour in the model.
  Treat the numbers as an order of magnitude; the panel shows the live savings estimate for your settings.

---

## 🇵🇱 Podsumowanie
Symulacja 7 dni na prawdziwych danych (09–15.10.2026), godzina po godzinie, z cenami znanymi tylko do chwili decyzji:

* **Tylko doładowanie (domyślnie)** – pompa decyduje sama, Pstryk AI tylko włącza 100 % do 55 °C w tanich godzinach:
  **91,19 zł zamiast 103,73 zł (−12 %)**, 0 godzin poniżej minimum, 23 godziny doładowania w tygodniu.
* **Pełne sterowanie** – 80,63 zł (−22 %), ale Pstryk AI przejmuje decyzje i częściej uruchamia sprężarkę.
* Przy małej różnicy cen (ok. 30 %) doładowanie się nie opłaca (niższy COP przy 55 °C) i nie jest planowane.
