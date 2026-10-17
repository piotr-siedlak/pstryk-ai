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
    },
    "switch": {
        "optimization_enabled": "Optymalizacja",
        "buffer_enabled": "Optymalizacja bufora",
        "mqtt_enabled": "Publikacja MQTT",
        "advisory_mode": "Tryb doradczy",
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
            "Cheapest-hour preferences and device profiles as a JSON list (name, power_kw, duration_h, consecutive, …) – format: docs/OPTIMIZATION.md.",
        ),
        (
            "Optymalizacja",
            "Preferencje tanich godzin i profile urządzeń jako lista JSON (name, power_kw, duration_h, consecutive, …) – format: docs/OPTIMIZATION.md.",
        ),
    ),
    "buffer": (
        ("Thermal buffer", "Advisory optimization of a heat-pump buffer. Hardware safety limits always remain local."),
        (
            "Bufor ciepła",
            "Doradcza optymalizacja bufora pompy ciepła. Zabezpieczenia sprzętowe zawsze pozostają lokalne.",
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

ERRORS = {
    "invalid_auth": ("Invalid API key", "Nieprawidłowy klucz API"),
    "cannot_connect": ("Cannot connect to Pstryk", "Brak połączenia z Pstryk"),
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


def build(lang: int) -> dict:
    def step(step_id: str) -> dict:
        title, desc = STEPS[step_id][lang] if step_id in STEPS else (MENU[step_id][lang], "")
        out = {"title": title, "description": desc}
        fields = STEP_FIELDS.get(step_id)
        if fields:
            out["data"] = {f: FIELDS[f][lang] for f in fields}
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
        s: step(s) for s in ["pstryk", "location", "market", "weather", "forecast", "optimization", "buffer", "mqtt"]
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
