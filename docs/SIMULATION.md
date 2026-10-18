# Simulation and benchmark of the heating strategies

Two scripts replay real data **hour by hour, as it would run live** (closed loop, model-predictive control):

* every hour the controller sees only the prices known at that time – today, plus tomorrow from 13:00 (Pstryk publication),
* it plans, applies the decision for the current hour, and the "real" buffer moves on with the measured outdoor temperature,
* the next hour starts from the resulting temperature (re-planning included, nothing is known in hindsight).

```bash
python scripts/benchmark_heating.py              # 3 × 4 weeks (winter, spring, autumn), with the optimum bound
python scripts/benchmark_heating.py --curve 0.4  # the same with a heating curve
python scripts/simulate_week.py                  # the last 7 days
```

Engine: `custom_components/pstryk_ai/optimization/simulation.py` (covered by `tests/test_v050_boost.py` and `tests/test_v060_physics.py`).

Data: PSE RCE (public) converted to a customer price with the default tariff – a stand-in for Pstryk prices, which cannot be fetched
without a key – and the Open-Meteo archive temperature (Warsaw area). Model: 500 L buffer, heat-pump setpoint 35 °C, minimum 30 °C,
9 kW_th / 3 kW_el heat pump, COP 3.0 (A7/W35), minimum modulation 30 %, building 0.2 kW/K, boost up to 55 °C, boost hours = cheapest
40 % of the next 24 h.

## Strategies

| Strategy | Who decides | What Pstryk AI sends |
|---|---|---|
| heat pump alone (reference) | the heat pump holds its setpoint | nothing |
| **Tylko doładowanie** (`boost`, default) | the heat pump; Pstryk AI adds **100 % boosts in cheap hours** up to an optimised temperature | `optimizer/buffer/boost` = 1/0, `boost_target` |
| Pełne sterowanie (`full`) | Pstryk AI every hour, incl. modulation | `should_heat`, `hp_modulation`, target |
| optimum (bound) | perfect foresight: one plan over the whole month with every price known | – (not achievable) |

## Result – 3 × 4 weeks of real data (v0.6.0)

Costs corrected for the different heat content at the end of the period.

**Fixed heat-pump setpoint**

| Period | Heat pump alone | Boost only | Full control | Optimum | Hours below minimum |
|---|---:|---:|---:|---:|---:|
| Winter 05.01–01.02 (avg −7.8 °C, min −23 °C) | 1434.36 zł | **1398.29 zł (−2.5 %)** | 1293.20 zł (−9.8 %) | 1292.43 zł | 0 / 0 / 0 |
| Spring 16.03–12.04 (prices down to −0.73 zł) | 305.03 zł | **242.47 zł (−20.5 %)** | 207.89 zł (−31.8 %) | 207.00 zł | 0 / 0 / 0 |
| Autumn 14.09–11.10 | 183.51 zł | **121.52 zł (−33.8 %)** | 97.63 zł (−46.8 %) | 97.90 zł | 0 / 0 / 0 |

**With a heating curve (slope 0.4 K/K)**

| Period | Heat pump alone | Boost only | Full control | Optimum |
|---|---:|---:|---:|---:|
| Winter | 1512.66 zł | **1470.37 zł (−2.8 %)** | 1368.55 zł (−9.5 %) | 1366.30 zł |
| Spring | 292.50 zł | **226.67 zł (−22.5 %)** | 193.94 zł (−33.7 %) | 193.38 zł |
| Autumn | 152.33 zł | **97.30 zł (−36.1 %)** | 76.01 zł (−50.1 %) | 75.82 zł |

* **Full control is within 0.1–0.4 % of the perfect-foresight optimum** in every season. Day-ahead prices are enough; a longer horizon,
  a better price forecast or a heavier solver cannot save more with this model.
* **Boost only** keeps the heat pump in charge and still saves 20–36 % outside deep winter. In deep frost there is little to gain
  with boosts: the heat pump already runs most of the day at reduced output and a hotter tank costs COP.

## Old (v0.5.0) vs new (v0.6.0) algorithm

Both drive the **same realistic heat pump** (output falls in frost, better COP at part load, cycling losses, optionally a heating curve).
The old planner assumed full output at any temperature, constant efficiency at any load and a fixed minimum.

| Period | Boost only v0.5 → v0.6 | Full control v0.5 → v0.6 |
|---|---|---|
| Winter | 1421.7 → **1398.3 zł** (saving vs heat pump alone 12.7 → **36.1 zł**) | 1338.1 zł with **62 h below minimum** (up to 3.3 K) → **1293.7 zł, 0 h** |
| Spring | 245.0 → **242.5 zł** | 218.2 zł (1 h below) → **207.6 zł** (−4.9 %) |
| Autumn | 125.3 → **121.6 zł** (−3.0 %) | 99.3 → **97.6 zł** |
| Winter, heating curve | 1487.8 → **1470.4 zł** | 1338.1 zł with **258 h below the required temperature** (up to 10 K) → 1369.5 zł, **0 h** |
| Spring, heating curve | 229.9 → **226.7 zł** | 218.2 → **193.6 zł** (−11.3 %) |
| Autumn, heating curve | 102.9 → **97.4 zł** (−5.3 %) | 99.3 → **75.3 zł** (−24.2 %) |

What changed the result:
* **Frost**: the old planner let the buffer drift down expecting 9 kW to recover it – at −20 °C the heat pump gives ~6 kW, so comfort
  failed for hours. The new one pre-charges in time.
* **Boost temperature**: the old boost always went to 55 °C. The new one chooses 40–55 °C per situation and skips boosts whose COP
  loss would eat the gain – in winter it boosted half as often (70 vs 136 h) and saved almost 3× more.
* **Part load and cycling**: running long at low power beats short full-power bursts; 5 modulation steps instead of 3.
* **Heating curve**: in mild weather the buffer may run cooler (better COP, lower losses), in frost it must be hotter.

## Last 7 days (10–16.10.2026)

| Strategy | Cost | Saving | Hours below minimum | Boost hours |
|---|---:|---:|---:|---:|
| heat pump alone | 108.59 zł | – | 0 | – |
| **boost only** | **98.68 zł** | **−9.1 %** | 0 | 21 |
| full control | 85.32 zł | −21.4 % | 0 | – |

## Caveats
RCE-based prices instead of real Pstryk prices; one building and heat-pump model; the simulated "reality" uses the same physics as the
planner (old vs new compares two planners on that physics). Treat the numbers as an order of magnitude – the panel shows the live savings
estimate for your settings. Set *Moc grzewcza przy −15 °C* and the heating curve to match your heat pump for the best plans.

---

## 🇵🇱 Podsumowanie
* Symulacja 3 × 4 tygodnie (zima, wiosna, jesień 2026) na prawdziwych danych, godzina po godzinie, bez wiedzy o przyszłości.
* **Tylko doładowanie** (domyślnie): −2,5 % zimą, −20,5 % wiosną, −33,8 % jesienią względem samej pompy, zawsze 0 godzin poniżej minimum.
* **Pełne sterowanie**: −9,8 % / −31,8 % / −46,8 % i tylko 0,1–0,4 % od teoretycznego optimum (pełna wiedza o cenach całego miesiąca).
* Nowy algorytm (v0.6) zna fizykę pompy: spadek mocy na mrozie, lepszy COP przy niższej mocy, straty taktowania, krzywą grzewczą,
  i sam dobiera temperaturę doładowania (40–55 °C). Stary w mroźnym styczniu dopuszczał 62 godziny poniżej minimum (z krzywą grzewczą 258).
