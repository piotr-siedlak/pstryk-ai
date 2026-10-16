# Installation

## Requirements
* Home Assistant 2025.6 or newer (tested with 2026.10).
* A Pstryk.pl contract and an API key generated in the Pstryk app.
* Optional: MQTT integration configured in Home Assistant (Mosquitto add-on or any broker).
* Optional, recommended: free ENTSO-E Transparency security token for day-ahead price history.

## HACS (custom repository)
1. HACS → ⋮ → *Custom repositories* → URL `https://github.com/piotr-siedlak/pstryk-ai`, category *Integration*.
2. Install **Pstryk AI**, restart Home Assistant.
3. *Settings → Devices & services → Add integration → Pstryk AI*.

## Manual
Copy `custom_components/pstryk_ai` into `<config>/custom_components/` and restart.

## Pstryk API key
Generate the key in the Pstryk app. The wizard validates it with **one** request (the free API allows 3 requests/hour). The key is stored in
the config entry, never logged, never published to MQTT and redacted from diagnostics. Do not paste it into public forums or repositories.

## ENTSO-E token
1. Register at <https://transparency.entsoe.eu/>.
2. E-mail `transparency@entsoe.eu` with subject “Restful API access” and your account e-mail (as documented by ENTSO-E).
3. Copy the *Web API Security Token* from *My Account Settings* into *Market data* step.

Without a token the integration uses PSE RCE as a **clearly labelled proxy** for training (`market_reference = pse_rce_proxy`) and shows
no `PUBLISHED_TGE` prices (only confirmed Pstryk prices and forecasts).

## First start
* Public history (PSE, ENTSO-E, Open-Meteo historical forecasts) is imported in the background (`Importuj dane historyczne`, ~1–3 min).
  **No Pstryk history is backfilled.**
* The model trains in an executor thread when the import finishes (seconds). Until then the seasonal baseline is used.
* Time zone of Home Assistant should be `Europe/Warsaw` (schedules use local HA time).
