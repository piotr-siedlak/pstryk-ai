"""Generate strings.json + translations/{en,pl}.json from one source of truth.

Entity names are Polish in every language (project requirement); config-flow
texts are localised.
Run: python scripts/gen_translations.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "pstryk_ai"

ENTITIES = {
    "sensor": {
        "current_buy_price": "Aktualna cena zakupu",
        "current_sell_price": "Aktualna cena sprzedaży",
        "current_all_in_price": "Aktualna cena całkowita (z dystrybucją)",
        "next_hour_price": "Cena w następnej godzinie",
        "average_today": "Średnia cena dzisiaj",
        "average_tomorrow": "Średnia cena jutro",
        "cheapest_hour_today": "Najtańsza godzina dzisiaj",
        "cheapest_hour_tomorrow": "Najtańsza godzina jutro",
        "cheapest_3h": "Najtańsze 3 godziny",
        "cheapest_6h": "Najtańsze 6 godzin",
        "cheapest_n_hours": "Najtańsze N godzin (24 h)",
        "most_expensive_hour": "Najdroższa godzina",
        "forecast_24h": "Prognoza ceny za 24 godziny",
        "forecast_48h": "Prognoza ceny za 48 godzin",
        "forecast_72h": "Prognoza ceny za 72 godziny",
        "forecast_7d": "Prognoza ceny za 7 dni",
        "average_7d": "Średnia prognozowana cena na 7 dni",
        "cheap_probability": "Prawdopodobieństwo taniej energii",
        "forecast_accuracy": "Dokładność prognoz",
        "forecast_confidence": "Pewność prognozy",
        "pstryk_api_status": "Status API Pstryk",
        "market_data_status": "Status danych TGE",
        "mqtt_status": "Status MQTT",
        "last_update": "Czas ostatniej aktualizacji",
        "buffer_target_temperature": "Zalecana temperatura bufora",
        "buffer_next_window": "Następne okno grzania",
        "buffer_temperature": "Temperatura bufora – góra",
        "buffer_bottom_temperature": "Temperatura bufora – dół",
        "buffer_soc": "Naładowanie bufora",
        "buffer_heater_power": "Grzałka bufora – zalecana moc",
        "dhw_top_temperature": "Temperatura CWU – góra",
        "dhw_bottom_temperature": "Temperatura CWU – dół",
        "dhw_soc": "Naładowanie CWU",
        "dhw_target_temperature": "Zalecana temperatura CWU",
        "dhw_next_window": "Następne grzanie CWU",
        "dhw_expected_cost": "Prognozowany koszt CWU",
        "dhw_plan_reason": "Uzasadnienie planu CWU",
        "dhw_heater_power": "Grzałka CWU – zalecana moc",
        "legionella": "Antylegionella – ostatni cykl",
        "valve_position": "Zawór pompy ciepła",
        "distribution_zone": "Strefa taryfy dystrybucyjnej",
        "pv_production_today": "Produkcja PV dziś (prognoza)",
        "pv_surplus_now": "Nadwyżka PV teraz",
        "hp_energy_today": "Zużycie pompy ciepła dziś",
        "hp_cost_today": "Koszt pompy ciepła dziś",
        "heaters_energy_today": "Zużycie grzałek dziś",
        "cost_yesterday": "Koszt energii wczoraj",
        "cost_previous_month": "Koszt energii w poprzednim miesiącu",
        "cost_12_months": "Koszt energii – ostatnie 12 miesięcy",
        "avg_daily_cost": "Średni dzienny koszt energii",
        "projected_month_cost": "Prognozowany koszt miesiąca",
        "learning_status": "Uczenie parametrów",
        "outdoor_temperature": "Temperatura zewnętrzna (odczyt)",
        "buffer_expected_cost": "Prognozowany koszt ogrzewania",
        "buffer_savings": "Szacowane oszczędności",
        "buffer_plan_reason": "Uzasadnienie planu bufora",
        "energy_import_today": "Zużycie energii dzisiaj",
        "energy_export_today": "Oddanie energii dzisiaj",
        "energy_balance_today": "Bilans energii dzisiaj",
        "cost_today": "Koszt energii dzisiaj",
        "sold_value_today": "Wartość sprzedanej energii dzisiaj",
        "balance_today": "Saldo finansowe dzisiaj",
        "energy_import_month": "Zużycie energii w tym miesiącu",
        "energy_export_month": "Oddanie energii w tym miesiącu",
        "energy_balance_month": "Bilans energii w tym miesiącu",
        "cost_month": "Koszt energii w tym miesiącu",
        "balance_month": "Saldo finansowe w tym miesiącu",
        "device_schedule": "Harmonogram: {name}",
    },
    "binary_sensor": {
        "cheap_now": "Tania energia teraz",
        "expensive_now": "Droga energia teraz",
        "pstryk_cheap_hour": "Tania godzina wg Pstryk",
        "tomorrow_confirmed": "Ceny na jutro potwierdzone",
        "buffer_should_heat": "Zalecane grzanie bufora",
        "dhw_should_heat": "Zalecane grzanie CWU",
        "buffer_heater_should_run": "Zalecana praca grzałki bufora",
        "dhw_heater_should_run": "Zalecana praca grzałki CWU",
    },
    "switch": {
        "optimization_enabled": "Optymalizacja",
        "buffer_enabled": "Optymalizacja bufora",
        "mqtt_enabled": "Publikacja MQTT",
        "advisory_mode": "Tryb doradczy",
        "dhw_enabled": "Optymalizacja CWU",
        "buffer_heater_enabled": "Grzałka bufora",
        "dhw_heater_enabled": "Grzałka CWU",
        "pv_enabled": "Autokonsumpcja PV",
        "power_limit_enabled": "Limit mocy przyłącza",
        "optimize_all_in": "Optymalizacja wg ceny z dystrybucją",
    },
    "button": {
        "recalculate_forecast": "Przelicz prognozę",
        "recalculate_schedule": "Przelicz harmonogram",
        "retrain_model": "Trenuj model prognozy",
        "import_history": "Importuj dane historyczne",
    },
    "number": {
        "buffer_max_t": "Maksymalna temperatura bufora",
        "buffer_min_t": "Minimalna temperatura bufora",
        "price_threshold": "Próg ceny",
        "cheap_hours": "Liczba najtańszych godzin",
    },
    "select": {
        "forecast_model": "Model prognozy",
        "buffer_strategy": "Strategia bufora",
    },
}

STATUS_STATES = {
    "ok": "OK",
    "pending": "Oczekiwanie",
    "error": "Błąd",
    "auth_error": "Błąd autoryzacji",
    "rate_limited": "Limit zapytań",
    "disabled": "Wyłączone",
    "disconnected": "Rozłączono",
    "not_configured": "Nieskonfigurowane",
}
SELECT_STATES = {
    "forecast_model": {"auto": "Automatyczny (zespół)", "baseline": "Bazowy sezonowy", "ridge": "Regresja grzbietowa"},
    "buffer_strategy": {"min_cost": "Minimalny koszt", "comfort": "Komfort"},
}

FIELDS = {
    "api_key": ("API key", "Klucz API"),
    "prosumer": ("Prosumer (energy export)", "Prosument (oddawanie energii)"),
    "vat_rate": ("VAT rate", "Stawka VAT"),
    "energy_margin_net": ("Energy margin (net)", "Marża za energię (netto)"),
    "excise_net": ("Excise duty (net)", "Akcyza (netto)"),
    "var_distribution_net": ("Variable distribution charge (net)", "Zmienna opłata dystrybucyjna (netto)"),
    "pstryk_price_includes_distribution": (
        "Pstryk price already includes distribution",
        "Cena Pstryk zawiera dystrybucję",
    ),
    "auto_calibrate_tariff": ("Auto-calibrate tariff locally (opt-in)", "Lokalna autokalibracja taryfy (opcjonalnie)"),
    "use_ha_location": ("Use Home Assistant location", "Użyj lokalizacji Home Assistant"),
    "latitude": ("Latitude", "Szerokość geograficzna"),
    "longitude": ("Longitude", "Długość geograficzna"),
    "market_provider": ("Day-ahead market data source", "Źródło cen rynku dnia następnego"),
    "entsoe_token": ("ENTSO-E security token", "Token ENTSO-E"),
    "pse_enabled": ("Use PSE API (demand, wind, PV, RCE)", "Użyj API PSE (zapotrzebowanie, wiatr, PV, RCE)"),
    "tge_enabled": ("Use TGE website (experimental)", "Użyj strony TGE (eksperymentalne)"),
    "eur_pln_rate": ("EUR/PLN rate (only if source is EUR)", "Kurs EUR/PLN (tylko gdy źródło w EUR)"),
    "weather_model": ("Weather model", "Model pogody"),
    "weather_refresh_hours": ("Weather refresh interval", "Interwał odświeżania pogody"),
    "history_days": ("History length", "Długość historii"),
    "forecast_horizon_hours": ("Forecast horizon", "Horyzont prognozy"),
    "forecast_model": ("Forecast model", "Model prognozy"),
    "auto_retrain": ("Automatic weekly retraining", "Automatyczne cotygodniowe trenowanie"),
    "risk_aversion": ("Risk aversion (forecast uncertainty)", "Awersja do ryzyka (niepewność prognozy)"),
    "max_speculative_hours": ("Max speculative postponement", "Maks. odkładanie na podstawie prognozy"),
    "cheap_hours_count": ("Number of cheapest hours", "Liczba najtańszych godzin"),
    "price_threshold": ("Absolute cheap price threshold", "Bezwzględny próg taniej ceny"),
    "device_profiles": ("Device profiles (JSON list)", "Profile urządzeń (lista JSON)"),
    "buffer_enabled": ("Enable buffer optimization", "Włącz optymalizację bufora"),
    "buffer_temperature_entity": ("Buffer temperature sensor", "Czujnik temperatury bufora"),
    "outdoor_temperature_entity": (
        "Outdoor temperature sensor (optional)",
        "Czujnik temperatury zewnętrznej (opcjonalnie)",
    ),
    "buffer_capacity_liters": ("Buffer volume", "Pojemność bufora"),
    "buffer_min_temperature": ("Minimum buffer temperature", "Minimalna temperatura bufora"),
    "buffer_max_temperature": ("Maximum buffer temperature", "Maksymalna temperatura bufora"),
    "buffer_target_temperature": ("Default target temperature", "Domyślna temperatura docelowa"),
    "heat_pump_electrical_power": ("Heat pump electrical power", "Moc elektryczna pompy ciepła"),
    "heat_pump_thermal_power": ("Heat pump thermal power", "Moc grzewcza pompy ciepła"),
    "heat_pump_cop": ("Nominal COP (A7/W35)", "Nominalny COP (A7/W35)"),
    "heat_pump_cop_curve": (
        "COP curve at W35, e.g. -15:2.0,-7:2.6,2:3.3,7:4.1",
        "Krzywa COP przy W35, np. -15:2.0,-7:2.6,2:3.3,7:4.1",
    ),
    "thermal_losses": ("Buffer standby losses", "Straty postojowe bufora"),
    "building_heat_loss_kw_per_k": ("Building heat demand per K", "Zapotrzebowanie budynku na ciepło na 1 K"),
    "heating_base_temperature": ("Heating base temperature", "Temperatura bazowa ogrzewania"),
    "minimum_runtime": ("Minimum compressor runtime", "Minimalny czas pracy sprężarki"),
    "minimum_offtime": ("Minimum compressor off time", "Minimalny czas postoju sprężarki"),
    "maximum_start_count": ("Maximum starts per day", "Maksymalna liczba startów na dobę"),
    "buffer_strategy": ("Buffer strategy", "Strategia bufora"),
    "mqtt_enabled": ("Publish to MQTT", "Publikuj do MQTT"),
    "mqtt_prefix": ("Topic prefix", "Prefiks tematów"),
    "mqtt_discovery": ("Home Assistant MQTT discovery (key values only)", "MQTT Discovery (tylko kluczowe wartości)"),
    "mqtt_qos": ("QoS", "QoS"),
    "mqtt_retain": ("Retain data topics", "Retain dla tematów z danymi"),
    "mqtt_evcc": ("EVCC-compatible price topic", "Temat cen zgodny z EVCC"),
}

STEP_FIELDS = {
    "user": [
        "api_key",
        "prosumer",
        "vat_rate",
        "energy_margin_net",
        "excise_net",
        "var_distribution_net",
        "pstryk_price_includes_distribution",
        "auto_calibrate_tariff",
    ],
    "pstryk": [
        "prosumer",
        "vat_rate",
        "energy_margin_net",
        "excise_net",
        "var_distribution_net",
        "pstryk_price_includes_distribution",
        "auto_calibrate_tariff",
    ],
    "location": ["use_ha_location", "latitude", "longitude"],
    "market": ["market_provider", "entsoe_token", "pse_enabled", "tge_enabled", "eur_pln_rate"],
    "weather": ["weather_model", "weather_refresh_hours", "history_days"],
    "forecast": ["forecast_horizon_hours", "forecast_model", "auto_retrain", "risk_aversion", "max_speculative_hours"],
    "optimization": ["cheap_hours_count", "price_threshold", "device_profiles"],
    "buffer": [
        "buffer_enabled",
        "buffer_temperature_entity",
        "outdoor_temperature_entity",
        "buffer_capacity_liters",
        "buffer_min_temperature",
        "buffer_max_temperature",
        "buffer_target_temperature",
        "heat_pump_electrical_power",
        "heat_pump_thermal_power",
        "heat_pump_cop",
        "heat_pump_cop_curve",
        "thermal_losses",
        "building_heat_loss_kw_per_k",
        "heating_base_temperature",
        "minimum_runtime",
        "minimum_offtime",
        "maximum_start_count",
        "buffer_strategy",
    ],
    "mqtt": ["mqtt_enabled", "mqtt_prefix", "mqtt_discovery", "mqtt_qos", "mqtt_retain", "mqtt_evcc"],
}

# canonical MQTT topics (kept in sync with mqtt/schemas.py by a test)
TOPICS = [
    "availability",
    "status",
    "prices/current",
    "prices/current/json",
    "prices/next",
    "prices/today",
    "prices/tomorrow",
    "prices/pstryk/buy",
    "prices/pstryk/sell",
    "prices/tge",
    "prices/forecast/7d",
    *[f"prices/forecast/day/{d}" for d in range(1, 8)],
    "cheap/now",
    "cheap/next_start",
    "cheap/best_2h",
    "cheap/best_4h",
    "cheap/best_6h",
    "cheap/best_24h",
    "cheap/schedule",
    "weather/current",
    "weather/forecast",
    "weather/temperature",
    "weather/wind",
    "weather/solar",
    "optimizer/buffer/should_heat",
    "optimizer/buffer/mode",
    "optimizer/buffer/target_temperature",
    "optimizer/buffer/next_start",
    "optimizer/buffer/next_stop",
    "optimizer/buffer/expected_cost",
    "optimizer/buffer/schedule",
    "forecast/status",
    "forecast/confidence",
    "forecast/last_update",
    "api/pstryk/status",
    "api/tge/status",
    "api/entsoe/status",
    "api/pse/status",
    "api/weather/status",
    "evcc/prices",
    "optimizer/buffer/heater/should_run",
    "optimizer/buffer/heater/power",
    "optimizer/buffer/soc",
    "optimizer/dhw/should_heat",
    "optimizer/dhw/mode",
    "optimizer/dhw/target_temperature",
    "optimizer/dhw/next_start",
    "optimizer/dhw/schedule",
    "optimizer/dhw/heater/should_run",
    "optimizer/dhw/heater/power",
    "optimizer/dhw/soc",
    "optimizer/valve",
    "spends/summary",
    "spends/daily",
    "spends/monthly",
    "heartbeat",
]

STEPS = {
    "user": (
        (
            "Pstryk – API key",
            "Enter your Pstryk API key (generated in the Pstryk app). The key is validated with one request and is never logged or published.",
        ),
        (
            "Pstryk – klucz API",
            "Podaj klucz API Pstryk (wygenerowany w aplikacji Pstryk). Klucz jest sprawdzany jednym zapytaniem i nigdy nie jest logowany ani publikowany.",
        ),
    ),
    "pstryk": (
        ("Pstryk and tariff", "Tariff parameters used to estimate prices that Pstryk has not confirmed yet."),
        ("Pstryk i taryfa", "Parametry taryfy używane do szacowania cen, których Pstryk jeszcze nie potwierdził."),
    ),
    "location": (
        ("Location", "Building location for local weather (heating demand, COP)."),
        ("Lokalizacja", "Lokalizacja budynku dla pogody lokalnej (zapotrzebowanie na ciepło, COP)."),
    ),
    "market": (
        (
            "Market data",
            "ENTSO-E (free token) is the recommended source of day-ahead history. PSE RCE is used only as a clearly labelled proxy. TGE website parsing is experimental and opt-in.",
        ),
        (
            "Dane rynkowe",
            "Zalecanym źródłem historii cen RDN jest ENTSO-E (bezpłatny token). PSE RCE służy wyłącznie jako oznaczony zamiennik. Parsowanie strony TGE jest eksperymentalne i opcjonalne.",
        ),
    ),
    "weather": (
        ("Weather", "Open-Meteo forecasts for the building and for representative regions of Poland."),
        ("Pogoda", "Prognozy Open-Meteo dla budynku i reprezentatywnych regionów Polski."),
    ),
    "forecast": (
        ("Forecasting", "Rolling 168 h probabilistic price forecast (P10/P50/P90)."),
        ("Prognozowanie", "Krocząca 168-godzinna prognoza probabilistyczna (P10/P50/P90)."),
    ),
    "optimization": (
        (
            "Optimization",
            "Cheapest-hour preferences and device profiles as a JSON list (name, power_kw, duration_h, consecutive, target, temperature_topic, temperature_key, …) – format: docs/OPTIMIZATION.md.",
        ),
        (
            "Optymalizacja",
            "Preferencje tanich godzin i profile urządzeń jako lista JSON (name, power_kw, duration_h, consecutive, target, temperature_topic, temperature_key, …) – format: docs/OPTIMIZATION.md.",
        ),
    ),
    "buffer": (
        (
            "Thermal buffer",
            "Advisory optimization of a heat-pump buffer. The buffer temperature is read from the exact MQTT topic (preferred, e.g. published by Loxone) or from a Home Assistant sensor. The payload can be a number (42.5) or JSON – then give the key, e.g. value or sensors.bufor. Hardware safety limits always remain local.",
        ),
        (
            "Bufor ciepła",
            "Doradcza optymalizacja bufora pompy ciepła. Temperatura bufora jest odczytywana z dokładnego tematu MQTT (zalecane, np. publikowanego przez Loxone) albo z czujnika Home Assistant. Wiadomość może być liczbą (42.5) lub JSON – wtedy podaj klucz, np. value albo sensors.bufor. Zabezpieczenia sprzętowe zawsze pozostają lokalne.",
        ),
    ),
    "mqtt": (
        ("MQTT", "Uses the MQTT broker configured in Home Assistant."),
        ("MQTT", "Używa brokera MQTT skonfigurowanego w Home Assistant."),
    ),
    "validate": (
        (
            "Test and validate",
            "Connectivity results:\n{results}\n\nSubmit to finish. Historical public market data will be imported in the background.",
        ),
        (
            "Test i weryfikacja",
            "Wyniki testów połączeń:\n{results}\n\nZatwierdź, aby zakończyć. Historyczne publiczne dane rynkowe zostaną zaimportowane w tle.",
        ),
    ),
    "reauth_confirm": (
        ("Re-authenticate Pstryk", "The Pstryk API key was rejected. Enter a new key."),
        ("Ponowna autoryzacja Pstryk", "Klucz API Pstryk został odrzucony. Podaj nowy klucz."),
    ),
}

STEPS["mqtt_topics"] = (
    (
        "MQTT topics",
        "Topic names relative to the prefix {prefix}. Start a name with / to make it absolute. Clear a field to stop publishing that topic. Retained messages on renamed or disabled topics are removed automatically.",
    ),
    (
        "Tematy MQTT",
        "Nazwy tematów względem prefiksu {prefix}. Nazwa zaczynająca się od / jest bezwzględna. Wyczyść pole, aby wyłączyć publikację tematu. Zachowane (retained) wiadomości ze zmienionych lub wyłączonych tematów są usuwane automatycznie.",
    ),
)
STEPS["panel"] = (
    ("Dashboard panel", "Show the Pstryk AI dashboard in the Home Assistant sidebar."),
    ("Panel", "Pokaż panel Pstryk AI na pasku bocznym Home Assistant."),
)
FIELDS["buffer_temperature_topic"] = (
    "Buffer temperature – MQTT topic (exact, e.g. loxone/bufor/temperatura)",
    "Temperatura bufora – temat MQTT (dokładny, np. loxone/bufor/temperatura)",
)
FIELDS["buffer_temperature_json_key"] = (
    "Buffer temperature – JSON key (only if the payload is JSON)",
    "Temperatura bufora – klucz JSON (tylko gdy wiadomość jest w JSON)",
)
FIELDS["outdoor_temperature_topic"] = (
    "Outdoor temperature – MQTT topic (optional)",
    "Temperatura zewnętrzna – temat MQTT (opcjonalnie)",
)
FIELDS["outdoor_temperature_json_key"] = (
    "Outdoor temperature – JSON key (optional)",
    "Temperatura zewnętrzna – klucz JSON (opcjonalnie)",
)
FIELDS["mqtt_input_max_age_minutes"] = (
    "Treat MQTT readings older than this as missing",
    "Odczyty MQTT starsze niż ta wartość traktuj jako brak danych",
)
STEP_FIELDS["buffer"] = [
    "buffer_enabled",
    "buffer_temperature_entity",
    "buffer_temperature_topic",
    "buffer_temperature_json_key",
    "outdoor_temperature_entity",
    "outdoor_temperature_topic",
    "outdoor_temperature_json_key",
    "mqtt_input_max_age_minutes",
] + [
    f
    for f in STEP_FIELDS["buffer"]
    if f not in ("buffer_enabled", "buffer_temperature_entity", "outdoor_temperature_entity")
]
FIELDS["show_panel"] = ("Show the Pstryk AI panel in the sidebar", "Pokaż panel Pstryk AI na pasku bocznym")
STEP_FIELDS["panel"] = ["show_panel"]

ERRORS = {
    "invalid_input_topic": (
        "Invalid MQTT topic – use an exact topic without # or +",
        "Nieprawidłowy temat MQTT – podaj dokładny temat bez # i +",
    ),
    "invalid_topic": ("Invalid topic (no #, + or empty levels)", "Nieprawidłowy temat (bez #, + i pustych poziomów)"),
    "duplicate_topic": ("Two topics resolve to the same name", "Dwa tematy mają tę samą nazwę"),
    "invalid_auth": ("Invalid API key", "Nieprawidłowy klucz API"),
    "cannot_connect": ("Cannot connect to Pstryk", "Brak połączenia z Pstryk"),
    "no_contract": (
        "Pstryk found no meter or active contract for this key",
        "Pstryk nie znalazł licznika ani aktywnej umowy dla tego klucza",
    ),
    "rate_limited": (
        "Pstryk rate limit reached – try again in an hour",
        "Osiągnięto limit zapytań Pstryk – spróbuj za godzinę",
    ),
    "invalid_entsoe": ("ENTSO-E token rejected", "Token ENTSO-E odrzucony"),
    "entsoe_token_required": ("ENTSO-E token required for this source", "To źródło wymaga tokenu ENTSO-E"),
    "invalid_profiles": ("Invalid device profiles JSON", "Nieprawidłowy JSON profili urządzeń"),
    "invalid_temperature_range": ("Maximum must be above minimum", "Maksimum musi być wyższe od minimum"),
    "invalid_prefix": ("Invalid MQTT topic prefix", "Nieprawidłowy prefiks tematu MQTT"),
}
ABORTS = {
    "already_configured": ("This Pstryk key is already configured", "Ten klucz Pstryk jest już skonfigurowany"),
    "reauth_successful": ("Re-authentication successful", "Ponowna autoryzacja zakończona"),
}
MENU = {
    "mqtt_topics": ("MQTT topics", "Tematy MQTT"),
    "panel": ("Dashboard panel", "Panel"),
    "pstryk": ("Pstryk and tariff", "Pstryk i taryfa"),
    "location": ("Location", "Lokalizacja"),
    "market": ("Market data", "Dane rynkowe"),
    "weather": ("Weather", "Pogoda"),
    "forecast": ("Forecasting", "Prognozowanie"),
    "optimization": ("Optimization", "Optymalizacja"),
    "buffer": ("Thermal buffer", "Bufor ciepła"),
    "mqtt": ("MQTT", "MQTT"),
}
SELECTORS = {
    "market_provider": {
        "entsoe": ("ENTSO-E (recommended)", "ENTSO-E (zalecane)"),
        "tge": ("TGE website (experimental)", "Strona TGE (eksperymentalne)"),
        "pse_rce": ("PSE RCE (proxy, not RDN)", "PSE RCE (zamiennik, nie RDN)"),
    },
    "weather_model": {
        "ecmwf_ifs025": ("ECMWF IFS 0.25°", "ECMWF IFS 0.25°"),
        "icon_seamless": ("DWD ICON", "DWD ICON"),
        "gfs_seamless": ("NOAA GFS", "NOAA GFS"),
        "best_match": ("Open-Meteo best match", "Open-Meteo najlepsze dopasowanie"),
    },
    "forecast_model": {
        "auto": ("Automatic (ensemble when it helps)", "Automatyczny (zespół, gdy poprawia wynik)"),
        "baseline": ("Seasonal baseline", "Bazowy sezonowy"),
        "ridge": ("Ridge regression", "Regresja grzbietowa"),
    },
    "buffer_strategy": {"min_cost": ("Minimum cost", "Minimalny koszt"), "comfort": ("Comfort", "Komfort")},
    "mqtt_qos": {"0": ("0", "0"), "1": ("1", "1"), "2": ("2", "2")},
}
ISSUES = {
    "mqtt_inputs_unavailable": (
        (
            "MQTT inputs unavailable",
            "MQTT topics for temperatures are configured but the MQTT integration is not set up.",
        ),
        ("Brak wejść MQTT", "Skonfigurowano tematy MQTT dla temperatur, ale integracja MQTT nie jest skonfigurowana."),
    ),
    "pstryk_auth_failed": (
        ("Pstryk API key rejected", "Pstryk rejected the API key. Re-authenticate the integration."),
        ("Klucz API Pstryk odrzucony", "Pstryk odrzucił klucz API. Ponownie uwierzytelnij integrację."),
    ),
    "entsoe_auth_failed": (
        ("ENTSO-E token rejected", "Update the ENTSO-E token in the integration options."),
        ("Token ENTSO-E odrzucony", "Zaktualizuj token ENTSO-E w opcjach integracji."),
    ),
}
SERVICES = {
    "recalculate_forecast": (
        ("Recalculate forecast", "Recompute the 168 h forecast and schedules."),
        ("Przelicz prognozę", "Przelicza 168-godzinną prognozę i harmonogramy."),
    ),
    "recalculate_schedule": (
        ("Recalculate schedule", "Recompute schedules with the current forecast."),
        ("Przelicz harmonogram", "Przelicza harmonogramy z bieżącą prognozą."),
    ),
    "retrain_model": (
        ("Retrain model", "Retrain the forecast models and rerun the backtest."),
        ("Trenuj model", "Trenuje modele prognozy i ponawia test historyczny."),
    ),
    "run_backtest": (
        ("Run backtest", "Rerun the rolling-origin backtest (retrains)."),
        ("Uruchom test historyczny", "Ponawia test historyczny (z ponownym trenowaniem)."),
    ),
    "import_history": (
        ("Import history", "Import public market, system and weather history."),
        ("Importuj historię", "Importuje publiczne dane rynkowe, systemowe i pogodowe."),
    ),
}
SERVICE_FIELDS = {
    "config_entry_id": (
        ("Config entry", "Limit to one config entry"),
        ("Wpis konfiguracji", "Ogranicz do jednego wpisu"),
    ),
    "days": (("Days", "Number of days to import"), ("Dni", "Liczba dni do importu")),
}


# ----------------------------------------------------------------------------- v0.4
FIELDS.update(
    {
        "buffer_top_entity": ("Buffer TOP temperature sensor (HA)", "Czujnik temperatury bufora – GÓRA (HA)"),
        "buffer_top_topic": (
            "Buffer TOP temperature – exact MQTT topic",
            "Temperatura bufora – GÓRA – dokładny temat MQTT",
        ),
        "buffer_top_json_key": ("Buffer TOP – JSON key (optional)", "Bufor GÓRA – klucz JSON (opcjonalnie)"),
        "buffer_bottom_entity": (
            "Buffer BOTTOM temperature sensor (HA, optional)",
            "Czujnik temperatury bufora – DÓŁ (HA, opcjonalnie)",
        ),
        "buffer_bottom_topic": (
            "Buffer BOTTOM temperature – exact MQTT topic (optional)",
            "Temperatura bufora – DÓŁ – dokładny temat MQTT (opcjonalnie)",
        ),
        "buffer_bottom_json_key": ("Buffer BOTTOM – JSON key (optional)", "Bufor DÓŁ – klucz JSON (opcjonalnie)"),
        "heat_pump_max_supply_temperature": (
            "Heat pump maximum supply temperature",
            "Maksymalna temperatura zasilania pompy ciepła",
        ),
        # pstryk spending
        "pstryk_spends": ("Pstryk spending (daily / monthly costs)", "Wydatki Pstryk (koszty dzienne i miesięczne)"),
        "pstryk_monthly_history": (
            "Monthly history – last 12 months (1 request per day)",
            "Historia miesięczna – ostatnie 12 miesięcy (1 zapytanie dziennie)",
        ),
        "pstryk_statistics_import": (
            "Import daily totals into HA long-term statistics (Energy dashboard)",
            "Import dziennych sum do statystyk HA (panel Energia)",
        ),
        # tariff
        "distribution_tariff": ("Distribution tariff", "Taryfa dystrybucyjna"),
        "distribution_rate_peak": (
            "Variable distribution – day / peak (net)",
            "Zmienna opłata dystrybucyjna – dzienna / szczyt (netto)",
        ),
        "distribution_rate_offpeak": (
            "Variable distribution – night / off-peak (net)",
            "Zmienna opłata dystrybucyjna – nocna / pozaszczyt (netto)",
        ),
        "distribution_rate_peak2": (
            "Variable distribution – G13 afternoon peak (net)",
            "Zmienna opłata dystrybucyjna – G13 szczyt popołudniowy (netto)",
        ),
        "distribution_offpeak_hours": ("Off-peak hours, e.g. 22-6,13-15", "Godziny strefy tańszej, np. 22-6,13-15"),
        "distribution_peak2_hours": (
            "G13 afternoon peak hours, e.g. 16-21",
            "Godziny szczytu popołudniowego G13, np. 16-21",
        ),
        "distribution_weekend_offpeak": ("Weekends and holidays are off-peak", "Weekendy i święta w strefie tańszej"),
        "optimize_on_all_in_price": (
            "Optimise on the price including distribution",
            "Optymalizuj według ceny z dystrybucją",
        ),
        # heaters
        **{
            f"{p}_heater_{k}": (en, pl)
            for p in ("buffer", "dhw")
            for k, en, pl in (
                ("enabled", "Use the heater", "Używaj grzałki"),
                ("kind", "Heater type", "Rodzaj grzałki"),
                (
                    "steps_kw",
                    "Power steps in kW (heat output), e.g. 2,4,6",
                    "Stopnie mocy w kW (moc grzewcza), np. 2,4,6",
                ),
                ("efficiency", "Efficiency (electric 1.0, gas ~0.92)", "Sprawność (elektryczna 1,0, gaz ~0,92)"),
                ("fuel_price", "Gas price per kWh of fuel", "Cena gazu za kWh paliwa"),
                (
                    "max_temperature",
                    "Maximum temperature for the heater (optional)",
                    "Maksymalna temperatura dla grzałki (opcjonalnie)",
                ),
                (
                    "command_topic",
                    "Command topic (exact, published only in control mode)",
                    "Temat sterowania (dokładny, publikowany tylko w trybie sterowania)",
                ),
                ("command_format", "Command format", "Format polecenia"),
                (
                    "state_topic",
                    "State / power topic for metering (optional)",
                    "Temat stanu / mocy do pomiaru zużycia (opcjonalnie)",
                ),
                ("state_json_key", "State – JSON key (optional)", "Stan – klucz JSON (opcjonalnie)"),
            )
        },
        # DHW
        "dhw_enabled": ("Optimise the hot-water tank (CWU)", "Optymalizuj zasobnik CWU"),
        "dhw_top_entity": ("CWU TOP temperature sensor (HA)", "Czujnik temperatury CWU – GÓRA (HA)"),
        "dhw_top_topic": ("CWU TOP temperature – exact MQTT topic", "Temperatura CWU – GÓRA – dokładny temat MQTT"),
        "dhw_top_json_key": ("CWU TOP – JSON key (optional)", "CWU GÓRA – klucz JSON (opcjonalnie)"),
        "dhw_bottom_entity": (
            "CWU BOTTOM temperature sensor (HA, optional)",
            "Czujnik temperatury CWU – DÓŁ (HA, opcjonalnie)",
        ),
        "dhw_bottom_topic": (
            "CWU BOTTOM temperature – exact MQTT topic (optional)",
            "Temperatura CWU – DÓŁ – dokładny temat MQTT (opcjonalnie)",
        ),
        "dhw_bottom_json_key": ("CWU BOTTOM – JSON key (optional)", "CWU DÓŁ – klucz JSON (opcjonalnie)"),
        "dhw_capacity_liters": ("Tank volume", "Pojemność zasobnika"),
        "dhw_min_temperature": ("Minimum temperature", "Minimalna temperatura"),
        "dhw_max_temperature": ("Maximum temperature", "Maksymalna temperatura"),
        "dhw_target_temperature": ("Default target temperature", "Domyślna temperatura docelowa"),
        "dhw_ready_times": (
            "Hot water ready at (local times, e.g. 06:00,19:00)",
            "Gotowość ciepłej wody o (np. 06:00,19:00)",
        ),
        "dhw_ready_temperature": ("Required temperature at ready times", "Wymagana temperatura w godzinach gotowości"),
        "dhw_liters_per_day": ("Hot water use per day (litres at 45 °C)", "Zużycie ciepłej wody na dobę (litry 45 °C)"),
        "dhw_losses": ("Tank standby losses", "Straty postojowe zasobnika"),
        "dhw_heat_pump_mode": ("Heat pump for CWU", "Pompa ciepła dla CWU"),
        "dhw_priority": ("CWU has priority over the buffer", "CWU ma priorytet nad buforem"),
        "dhw_valve_command_topic": (
            "Switching-valve command topic (optional, control mode)",
            "Temat sterowania zaworem przełączającym (opcjonalnie, tryb sterowania)",
        ),
        "legionella_enabled": ("Legionella protection cycle", "Cykl antylegionella"),
        "legionella_temperature": ("Legionella temperature", "Temperatura antylegionella"),
        "legionella_interval_days": ("Legionella interval", "Odstęp cyklu antylegionella"),
        # power
        "power_limit_enabled": ("Respect the connection power limit", "Uwzględniaj limit mocy przyłącza"),
        "power_limit_kw": ("Connection power limit", "Limit mocy przyłącza"),
        "base_load_kw": ("Typical household base load", "Typowe obciążenie podstawowe domu"),
        "heat_pump_power_entity": (
            "Heat pump power sensor (HA, optional)",
            "Czujnik mocy pompy ciepła (HA, opcjonalnie)",
        ),
        "heat_pump_power_topic": (
            "Heat pump power – exact MQTT topic (optional)",
            "Moc pompy ciepła – dokładny temat MQTT (opcjonalnie)",
        ),
        "heat_pump_power_json_key": (
            "Heat pump power – JSON key (optional)",
            "Moc pompy ciepła – klucz JSON (opcjonalnie)",
        ),
        "power_unit": ("Unit of power readings", "Jednostka odczytów mocy"),
        # PV
        "pv_enabled": ("Use PV surplus (self-consumption)", "Wykorzystuj nadwyżkę PV (autokonsumpcja)"),
        "pv_kwp": ("PV installation size", "Moc instalacji PV"),
        "pv_performance_ratio": ("Performance ratio", "Współczynnik sprawności instalacji"),
        # learning
        "learn_losses": (
            "Learn building heat demand and storage losses",
            "Ucz zapotrzebowania budynku i strat zasobnika",
        ),
        "learn_dhw_profile": ("Learn hot-water usage profile", "Ucz profilu zużycia ciepłej wody"),
        "learn_cop": (
            "Learn heat pump efficiency (needs power metering)",
            "Ucz sprawności pompy ciepła (wymaga pomiaru mocy)",
        ),
        "apply_learned_values": ("Use learned values in planning", "Używaj wyuczonych wartości w planowaniu"),
        # notifications
        "notify_tomorrow_prices": ("Tomorrow's prices summary", "Podsumowanie cen na jutro"),
        "notify_negative_prices": ("Negative prices tomorrow", "Ujemne ceny jutro"),
        "notify_local_control": ("Fallback to local control", "Przejście na sterowanie lokalne"),
        "notify_stale_data": ("Stale Pstryk data", "Nieaktualne dane Pstryk"),
        "notify_service": (
            "Notify service (e.g. notify.mobile_app_phone; empty = HA notification)",
            "Usługa powiadomień (np. notify.mobile_app_telefon; puste = powiadomienie HA)",
        ),
        "mqtt_heartbeat": (
            "MQTT heartbeat every 60 s (for Loxone watchdog)",
            "Heartbeat MQTT co 60 s (dla watchdoga Loxone)",
        ),
    }
)
STEP_FIELDS["pstryk"] = STEP_FIELDS["pstryk"] + ["pstryk_spends", "pstryk_monthly_history", "pstryk_statistics_import"]
STEP_FIELDS["user"] = STEP_FIELDS["user"] + ["pstryk_spends", "pstryk_monthly_history", "pstryk_statistics_import"]
STEP_FIELDS["buffer"] = [
    "buffer_enabled",
    "buffer_top_entity",
    "buffer_bottom_entity",
    "outdoor_temperature_entity",
    "buffer_top_topic",
    "buffer_top_json_key",
    "buffer_bottom_topic",
    "buffer_bottom_json_key",
    "outdoor_temperature_topic",
    "outdoor_temperature_json_key",
    "heat_pump_max_supply_temperature",
    "mqtt_input_max_age_minutes",
] + [
    f
    for f in STEP_FIELDS["buffer"]
    if not f.startswith(("buffer_temperature", "outdoor_temperature", "buffer_enabled", "mqtt_input_max_age"))
]
for _p in ("buffer", "dhw"):
    STEP_FIELDS[f"{_p}_heater"] = [k for k in FIELDS if k.startswith(f"{_p}_heater_")]
STEP_FIELDS["dhw"] = [k for k in FIELDS if k.startswith(("dhw_", "legionella_")) and "_heater_" not in k]
STEP_FIELDS["tariff"] = [k for k in FIELDS if k.startswith("distribution_")] + ["optimize_on_all_in_price"]
STEP_FIELDS["power"] = [
    "power_limit_enabled",
    "power_limit_kw",
    "base_load_kw",
    "heat_pump_power_entity",
    "heat_pump_power_topic",
    "heat_pump_power_json_key",
    "power_unit",
]
STEP_FIELDS["pv"] = ["pv_enabled", "pv_kwp", "pv_performance_ratio", "base_load_kw"]
STEP_FIELDS["learning"] = ["learn_losses", "learn_dhw_profile", "learn_cop", "apply_learned_values"]
STEP_FIELDS["notifications"] = [
    "notify_tomorrow_prices",
    "notify_negative_prices",
    "notify_local_control",
    "notify_stale_data",
    "mqtt_heartbeat",
    "notify_service",
]
STEPS.update(
    {
        "tariff": (
            (
                "Distribution tariff",
                "Time-of-use variable distribution charge. Hours are local, ranges like 22-6,13-15 (end hour exclusive). With optimisation on the all-in price the cheapest hours include distribution.",
            ),
            (
                "Taryfa dystrybucyjna",
                "Zmienna opłata dystrybucyjna zależna od strefy. Godziny lokalne, zakresy jak 22-6,13-15 (godzina końcowa wyłączna). Przy optymalizacji wg ceny z dystrybucją najtańsze godziny uwzględniają dystrybucję.",
            ),
        ),
        "buffer_heater": (
            (
                "Buffer heater",
                "Electric element or gas boiler heating the buffer. Commands go to the command topic only when advisory mode is off.",
            ),
            (
                "Grzałka bufora",
                "Grzałka elektryczna lub kocioł gazowy grzejący bufor. Polecenia trafiają na temat sterowania tylko przy wyłączonym trybie doradczym.",
            ),
        ),
        "dhw_heater": (
            (
                "CWU heater",
                "Electric element or gas boiler heating the hot-water tank (also used for legionella above the heat pump limit).",
            ),
            (
                "Grzałka CWU",
                "Grzałka elektryczna lub kocioł gazowy grzejący zasobnik CWU (używana też do antylegionelli powyżej limitu pompy).",
            ),
        ),
        "dhw": (
            (
                "Hot water (CWU)",
                "Second storage: drinkable hot-water tank with top/bottom sensors, ready times and an optional legionella cycle. With 'valve' the heat pump serves either the buffer or CWU in each hour.",
            ),
            (
                "Ciepła woda (CWU)",
                "Drugi zasobnik: ciepła woda użytkowa z czujnikami góra/dół, godzinami gotowości i opcjonalnym cyklem antylegionella. Przy trybie 'zawór' pompa ciepła w danej godzinie grzeje bufor albo CWU.",
            ),
        ),
        "power": (
            (
                "Power limit and metering",
                "Connection limit for heat pump + heaters + devices, and the optional heat-pump power reading used for real consumption and learning.",
            ),
            (
                "Limit mocy i pomiary",
                "Limit przyłącza dla pompy, grzałek i urządzeń oraz opcjonalny odczyt mocy pompy ciepła do rzeczywistego zużycia i uczenia.",
            ),
        ),
        "pv": (
            (
                "PV self-consumption",
                "PV production is estimated from the solar radiation forecast. Energy above the base load is valued at the Pstryk sell price for flexible loads.",
            ),
            (
                "Autokonsumpcja PV",
                "Produkcja PV jest szacowana z prognozy promieniowania. Energia ponad obciążenie podstawowe jest wyceniana dla odbiorników elastycznych po cenie sprzedaży Pstryk.",
            ),
        ),
        "learning": (
            (
                "Learning",
                "Learn parameters from measured temperatures (and power, if available). Learned values are used only when enabled below and after enough data.",
            ),
            (
                "Uczenie",
                "Uczenie parametrów z mierzonych temperatur (i mocy, jeśli dostępna). Wyuczone wartości są używane tylko po włączeniu poniżej i po zebraniu wystarczającej ilości danych.",
            ),
        ),
        "notifications": (
            ("Notifications", "Choose which notifications to send."),
            ("Powiadomienia", "Wybierz, które powiadomienia wysyłać."),
        ),
    }
)
MENU.update(
    {
        "tariff": ("Distribution tariff", "Taryfa dystrybucyjna"),
        "buffer_heater": ("Buffer heater", "Grzałka bufora"),
        "dhw": ("Hot water (CWU)", "Ciepła woda (CWU)"),
        "dhw_heater": ("CWU heater", "Grzałka CWU"),
        "power": ("Power limit and metering", "Limit mocy i pomiary"),
        "pv": ("PV self-consumption", "Autokonsumpcja PV"),
        "learning": ("Learning", "Uczenie"),
        "notifications": ("Notifications", "Powiadomienia"),
    }
)
ERRORS.update(
    {
        "invalid_steps": ("Enter power steps like 2,4,6", "Podaj stopnie mocy jak 2,4,6"),
        "invalid_number": ("Enter a number", "Podaj liczbę"),
        "invalid_times": ("Enter times like 06:00,19:00", "Podaj godziny jak 06:00,19:00"),
        "invalid_hours": ("Enter hour ranges like 22-6,13-15", "Podaj zakresy godzin jak 22-6,13-15"),
        "invalid_notify_service": (
            "Use a notify service, e.g. notify.mobile_app_phone",
            "Podaj usługę notify, np. notify.mobile_app_telefon",
        ),
    }
)
SELECTORS.update(
    {
        "heater_kind": {"electric": ("Electric", "Elektryczna"), "gas": ("Gas boiler", "Kocioł gazowy")},
        "command_format": {"binary": ("On/off (1/0)", "Wł./wył. (1/0)"), "power_kw": ("Power in kW", "Moc w kW")},
        "dhw_heat_pump_mode": {
            "valve": ("Shared heat pump with switching valve", "Wspólna pompa ciepła z zaworem przełączającym"),
            "none": ("Heat pump does not heat CWU (heater only)", "Pompa nie grzeje CWU (tylko grzałka)"),
        },
        "power_unit": {"kW": ("kW", "kW"), "W": ("W", "W")},
        "distribution_tariff": {
            "none": ("Flat rate (from the Pstryk step)", "Stała stawka (z kroku Pstryk)"),
            "G11": ("G11", "G11"),
            "G12": ("G12", "G12"),
            "G12w": ("G12w", "G12w"),
            "G13": ("G13", "G13"),
        },
    }
)
ENUM_STATES = {
    "valve_position": {"buffer": "Bufor", "dhw": "CWU", "idle": "Postój"},
    "distribution_zone": {
        "flat": "Stała",
        "peak": "Szczyt / dzienna",
        "offpeak": "Pozaszczyt / nocna",
        "peak2": "Szczyt popołudniowy",
    },
}


def build(lang: int) -> dict:
    def step(step_id: str) -> dict:
        title, desc = STEPS[step_id][lang] if step_id in STEPS else (MENU[step_id][lang], "")
        out = {"title": title, "description": desc}
        fields = STEP_FIELDS.get(step_id)
        if fields:
            out["data"] = {f: FIELDS[f][lang] for f in fields}
        if step_id == "mqtt_topics":
            out["data"] = {"topic_" + t.replace("/", "_"): t for t in TOPICS}
        if step_id == "reauth_confirm":
            out["data"] = {"api_key": FIELDS["api_key"][lang]}
        return out

    entity: dict = {}
    for platform, items in ENTITIES.items():
        entity[platform] = {}
        for key, name in items.items():
            entry: dict = {"name": name}
            if key in ("pstryk_api_status", "market_data_status", "mqtt_status"):
                entry["state"] = STATUS_STATES
            if key in SELECT_STATES:
                entry["state"] = SELECT_STATES[key]
            if key in ENUM_STATES:
                entry["state"] = ENUM_STATES[key]
            entity[platform][key] = entry
    config_steps = {
        s: step(s)
        for s in [
            "user",
            "location",
            "market",
            "weather",
            "forecast",
            "optimization",
            "buffer",
            "mqtt",
            "validate",
            "reauth_confirm",
        ]
    }
    option_steps = {
        s: step(s)
        for s in [
            "pstryk",
            "tariff",
            "location",
            "market",
            "weather",
            "forecast",
            "optimization",
            "buffer",
            "buffer_heater",
            "dhw",
            "dhw_heater",
            "power",
            "pv",
            "learning",
            "notifications",
            "mqtt",
            "mqtt_topics",
            "panel",
        ]
    }
    option_steps["init"] = {"title": "Pstryk AI", "menu_options": {k: v[lang] for k, v in MENU.items()}}
    return {
        "config": {
            "step": config_steps,
            "error": {k: v[lang] for k, v in ERRORS.items()},
            "abort": {k: v[lang] for k, v in ABORTS.items()},
        },
        "options": {"step": option_steps, "error": {k: v[lang] for k, v in ERRORS.items()}},
        "selector": {k: {"options": {o: t[lang] for o, t in opts.items()}} for k, opts in SELECTORS.items()},
        "entity": entity,
        "issues": {k: {"title": v[lang][0], "description": v[lang][1]} for k, v in ISSUES.items()},
        "exceptions": {
            "no_entry": {"message": ("No loaded Pstryk AI entry", "Brak załadowanego wpisu Pstryk AI")[lang]}
        },
        "services": {
            k: {
                "name": v[lang][0],
                "description": v[lang][1],
                "fields": {
                    f: {"name": SERVICE_FIELDS[f][lang][0], "description": SERVICE_FIELDS[f][lang][1]}
                    for f in (["config_entry_id", "days"] if k == "import_history" else ["config_entry_id"])
                },
            }
            for k, v in SERVICES.items()
        },
    }


def main() -> None:
    en, pl = build(0), build(1)
    (ROOT / "translations").mkdir(exist_ok=True)
    for path, data in (
        (ROOT / "strings.json", en),
        (ROOT / "translations" / "en.json", en),
        (ROOT / "translations" / "pl.json", pl),
    ):
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
