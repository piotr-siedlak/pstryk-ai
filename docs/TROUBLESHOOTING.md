# Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `Status API Pstryk = rate_limited` | Budget used (2 req/h) or HTTP 429 – the integration waits for `Retry-After`. Do not run other Pstryk integrations with the same key, or accept slower updates. |
| `auth_error` + repair issue | Key revoked/invalid → *Reconfigure / re-authenticate*. |
| Tomorrow still forecast after 14:00 | Pstryk publishes after the auction; placeholder values are not accepted as confirmed. Retries run at :02 and :32 until 18:00. |
| No `PUBLISHED_TGE` prices | No ENTSO-E token and TGE disabled – expected. RCE is never shown as published RDN. |
| Forecast = `seasonal_baseline` only | Not enough history yet, or ridge did not beat the baseline in the backtest (by design). See *Dokładność prognoz* attributes. |
| `Status MQTT = not_configured` | MQTT integration not set up in HA. |
| Buffer `mode = fallback` | Buffer temperature sensor missing/unavailable or price data stale – Loxone must use its local thermostat. |
| Wrong local hours | Set HA time zone to `Europe/Warsaw`. |
| TGE `error` | The site may block automated clients; switch to ENTSO-E. |

Download diagnostics (*Device → Download diagnostics*): secrets and coordinates are redacted; it contains provider status, budget,
seen price fields, timeline source counts, model metrics and history sizes.

Debug logging:

```yaml
logger:
  logs:
    custom_components.pstryk_ai: debug
```
