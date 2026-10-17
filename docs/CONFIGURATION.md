# Configuration

The wizard has 9 steps; every option except the API key stays editable via *Configure* (menu).

| Step | Options |
|---|---|
| 1 Pstryk | API key (validated), prosumer, VAT, energy margin (net PLN/kWh), excise (default 0.005), variable distribution (net), *Pstryk price includes distribution*, *local tariff auto-calibration* (opt-in) |
| 2 Location | HA location or manual coordinates |
| 3 Market data | source `entsoe` (recommended) / `tge` (experimental) / `pse_rce` (proxy), ENTSO-E token, PSE on/off, TGE on/off, EUR/PLN rate |
| 4 Weather | model (ECMWF IFS 0.25°, ICON, GFS, best match), refresh interval, history length |
| 5 Forecasting | horizon (24–168 h), model (`auto`/`baseline`/`ridge`), weekly retraining, risk aversion, max speculative postponement |
| 6 Optimization | number of cheapest hours, absolute threshold, device profiles (JSON) |
| 7 Thermal buffer | enable, buffer & outdoor sensors, volume, min/max/target, HP electric/thermal power, COP or COP curve, losses, building heat loss coefficient, base temperature, min run/off, max starts, strategy |
| 8 MQTT | enable, prefix, discovery, QoS, retain, EVCC topic |
| 9 Validate | connectivity results for PSE, Open-Meteo, MQTT, ENTSO-E |

Additional options (menu only):

| Option | Purpose |
|---|---|
| MQTT topics | rename (relative or absolute) or disable each of the 46 topics |
| Panel | show/hide the *Pstryk AI* sidebar panel |

## Price-source precedence
1. `ACTUAL_PSTRYK` – confirmed customer price from Pstryk (`price_gross`, gross, energy component).
2. `PUBLISHED_TGE` – published day-ahead market price (ENTSO-E or TGE) converted with the tariff: `(market/1000 + margin + excise)·(1+VAT)`.
3. `MODEL_FORECAST` – ensemble/ridge forecast converted with the tariff.
4. `FALLBACK_FORECAST` – seasonal baseline.
5. `UNAVAILABLE`.

`Aktualna cena całkowita (z dystrybucją)` adds the configured variable distribution charge (gross) unless the Pstryk price already includes it.
Sell price for non-confirmed hours follows Pstryk's documented formula `max(TGE, 0)·(1+VAT)`.

## Runtime controls (no reload)
Switches *Optymalizacja, Optymalizacja bufora, Publikacja MQTT, Tryb doradczy*; numbers *Maksymalna/Minimalna temperatura bufora, Próg ceny,
Liczba najtańszych godzin*; selects *Model prognozy, Strategia bufora*; buttons *Przelicz prognozę, Przelicz harmonogram, Trenuj model, Importuj dane*.

## Services
`pstryk_ai.recalculate_forecast`, `pstryk_ai.recalculate_schedule`, `pstryk_ai.retrain_model`, `pstryk_ai.run_backtest`,
`pstryk_ai.import_history` (`days`: 30–1100). Optional `config_entry_id`.

## Events
`pstryk_ai_prices_confirmed` (tomorrow's Pstryk prices arrived), `pstryk_ai_plan_updated` (every recomputation, with `reason`).
