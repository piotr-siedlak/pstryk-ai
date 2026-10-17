# Pstryk AI – inteligentne zarządzanie energią dla Home Assistant

Integracja dla klientów [Pstryk.pl](https://pstryk.pl). Łączy **potwierdzone ceny Pstryk** z publicznymi danymi rynku, systemu
elektroenergetycznego i pogody, tworzy **kroczącą prognozę cen na 7 dni (168 h)** z przedziałami P10/P50/P90, wyznacza najtańsze okresy,
planuje pracę urządzeń i **bufora ciepła**, a wyniki udostępnia w Home Assistant i przez **MQTT** (Loxone, Node-RED, ioBroker, EVCC).

> **Pstryk jest nadrzędnym źródłem rzeczywistych cen.** Dane TGE/ENTSO-E/PSE i pogoda służą do prognozowania przyszłości.
> Prognoza nigdy nie jest prezentowana jako cena potwierdzona.

## Instalacja
1. HACS → ⋮ → *Własne repozytoria* → `https://github.com/piotr-siedlak/pstryk-ai`, kategoria *Integracja* → zainstaluj → restart HA.
2. *Ustawienia → Urządzenia i usługi → Dodaj integrację → Pstryk AI*.
3. Strefa czasowa HA: `Europe/Warsaw`.

> HACS instaluje wyłącznie z **publicznego** repozytorium GitHub. Dopóki repozytorium jest prywatne, skopiuj katalog `custom_components/pstryk_ai` do `<config>/custom_components/` i zrestartuj HA.

Wymagania: Home Assistant 2026.2+ (testowane 2026.2 i 2026.10), klucz API Pstryk; opcjonalnie MQTT i bezpłatny token ENTSO-E (zalecany).

### Klucz API Pstryk
Klucz generujesz w aplikacji Pstryk. Kreator sprawdza go **jednym** zapytaniem (darmowe API: 3 zapytania/godz.). Klucz nie jest
logowany, publikowany w MQTT ani w diagnostyce. Nie umieszczaj go w publicznych repozytoriach.

### Token ENTSO-E
Rejestracja na <https://transparency.entsoe.eu/>, e-mail do `transparency@entsoe.eu` z tematem „Restful API access”, następnie token z
*My Account Settings*. Bez tokenu integracja używa **PSE RCE jako oznaczonego zamiennika** do trenowania modelu (RCE ≠ RDN!) i nie pokazuje
cen „opublikowanych na giełdzie”.

## Kreator konfiguracji (wszystko edytowalne później)
1. **Pstryk** – klucz, prosument, VAT, marża, akcyza, zmienna opłata dystrybucyjna, czy cena Pstryk zawiera dystrybucję, opcjonalna lokalna kalibracja taryfy.
2. **Lokalizacja** – z HA lub ręczna.
3. **Dane rynkowe** – ENTSO-E / TGE (eksperymentalnie) / PSE RCE, token, PSE, kurs EUR/PLN.
4. **Pogoda** – model (ECMWF, ICON, GFS), odświeżanie, długość historii.
5. **Prognozowanie** – horyzont, model, automatyczne trenowanie, awersja do ryzyka, maks. odkładanie decyzji.
6. **Optymalizacja** – liczba najtańszych godzin, próg ceny, profile urządzeń (JSON).
7. **Bufor ciepła** – czujniki, pojemność, temperatury, moc i COP pompy (lub krzywa COP), straty, zapotrzebowanie budynku, min. czas pracy/postoju, maks. starty, strategia.
8. **MQTT** – prefiks, discovery, QoS, retain, temat EVCC.
9. **Test i weryfikacja** – wyniki połączeń.

## Pierwszeństwo źródeł cen
`ACTUAL_PSTRYK` (potwierdzona) > `PUBLISHED_TGE` (opublikowana cena giełdowa przeliczona taryfą – szacunek) > `MODEL_FORECAST` >
`FALLBACK_FORECAST` (model bazowy) > `UNAVAILABLE`. Każdy sensor i rekord MQTT ma pole `source` i `quality`.

## Encje (wybrane)
Aktualna cena zakupu / sprzedaży / całkowita (z dystrybucją), Cena w następnej godzinie, Średnia cena dzisiaj/jutro, Najtańsza godzina
dzisiaj/jutro, Najtańsze 3/6/N godzin, Najdroższa godzina, Prognoza ceny za 24/48/72 godziny i 7 dni, Średnia prognozowana cena na 7 dni,
Prawdopodobieństwo taniej energii, Dokładność prognoz, Pewność prognozy, Status API Pstryk, Status danych TGE, Status MQTT, Czas ostatniej
aktualizacji, Zalecane grzanie bufora, Zalecana temperatura bufora, Następne okno grzania, Prognozowany koszt ogrzewania, Szacowane
oszczędności, zużycie/oddanie/koszt/saldo dzisiaj i w miesiącu, Harmonogram: <urządzenie>.
Sterowanie: przełączniki Optymalizacja, Optymalizacja bufora, Publikacja MQTT, Tryb doradczy; liczby: min/maks temperatura bufora, próg
ceny, liczba najtańszych godzin; wybór modelu i strategii; przyciski przeliczenia, trenowania i importu historii.

Identyfikatory encji są stałe, np. `sensor.pstryk_ai_current_buy_price`, `binary_sensor.pstryk_ai_buffer_should_heat`.

## Harmonogram obliczeń
00:05 zmiana doby · 06:00 i 18:00 pogoda + plan PSE · 10:45 Fixing I · **13:00 główne przeliczenie** · od 13:00 do 17:59 ponawianie
pobrania cen Pstryk na jutro (:02 i :32) aż do potwierdzenia · 14:05 Fixing II · wartości sensorów zmieniają się dokładnie na granicy godzin
bez odpytywania API. Godzina 13:00 nie jest traktowana jako gwarancja dostępności cen.

## MQTT (prefiks `pstryk_ai/home`)
`prices/current|next|today|tomorrow|pstryk/buy|pstryk/sell|tge|forecast/7d|forecast/day/1..7`, `cheap/now|next_start|best_2h|best_4h|best_6h|best_24h|schedule`,
`weather/current|forecast|temperature|wind|solar`, `optimizer/buffer/should_heat|mode|target_temperature|next_start|next_stop|expected_cost|schedule`,
`status`, `availability`, `forecast/status|confidence|last_update`, `api/pstryk/status`, `api/tge/status`, opcjonalnie `evcc/prices`.
Szczegóły i przykłady: [docs/MQTT_TOPICS.md](docs/MQTT_TOPICS.md). `should_heat` nie jest retained i wygasa po ~75 min.

## Loxone
Przykład logiki z watchdogiem świeżości i blokadami: [examples/loxone.md](examples/loxone.md).
Zabezpieczenia temperatur, pompy obiegowe, mieszacze i źródła ciepła **muszą działać niezależnie od MQTT**.

## Prognoza – jak jest liczona i jak dokładna
Model bazowy sezonowy + osobna regresja grzbietowa dla każdego dnia horyzontu (1–7) + zespół używany **tylko wtedy, gdy test historyczny
pokazuje poprawę**. Dane wejściowe: historia cen, kalendarz (święta PL), plan PSE (zapotrzebowanie, wiatr, PV, wymiana) na ~7 dni, pogoda
z 9 regionów Polski. Test historyczny na danych publicznych (97 dni prognoz, 2026): MAE ≈ 85–95 PLN/MWh dla dni 1–7 vs 125–136 PLN/MWh
modelu bazowego; pokrycie przedziału P10–P90 ≈ 75 %. **Dni 2–7 w teście są optymistyczne** (archiwalne prognozy o krótszym wyprzedzeniu) –
miarodajna jest dokładność „na żywo” (atrybut `live_mae` sensora *Dokładność prognoz*). Szczegóły: [docs/FORECASTING.md](docs/FORECASTING.md).

## Bufor ciepła
Model energii wody (`0,001163 kWh/(l·K)`), straty postojowe, zapotrzebowanie budynku zależne od temperatury zewnętrznej, COP zależny od
temperatury zewnętrznej i zasilania (wyższa temperatura bufora = gorszy COP), minimalny czas pracy/postoju, optymalizacja w horyzoncie
kroczącym (MPC). Porównanie kosztu z termostatem bez optymalizacji. Opis: [docs/OPTIMIZATION.md](docs/OPTIMIZATION.md).

**Tryb doradczy jest domyślny.** Brak czujnika lub nieaktualne dane → `mode = fallback`, `should_heat = 0` = „steruj lokalnie”.

## Prywatność i warunki
Użytek prywatny i niekomercyjny zgodnie z [regulaminem API Pstryk](https://pstryk.pl/regulamin-api). Dane Pstryk są przechowywane lokalnie
(14 dni), nie służą do trenowania modelu i nie opuszczają Twojego HA/brokera MQTT. Historia jest importowana wyłącznie z publicznych źródeł
(ENTSO-E, PSE, Open-Meteo). Źródła danych: Pstryk, ENTSO-E Transparency Platform, PSE S.A., TGE S.A., Open-Meteo.com (CC BY 4.0).

## Rozwiązywanie problemów
Zobacz [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md). Diagnostyka (*Urządzenie → Pobierz diagnostykę*) nie zawiera kluczy ani współrzędnych.

Projekt niezależny, niepowiązany z Pstryk, TGE, PSE ani ENTSO-E. Licencja MIT.
