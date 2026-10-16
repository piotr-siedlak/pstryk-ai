"""Diagnostics (secrets redacted)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.core import HomeAssistant

from . import PstrykAIConfigEntry
from .const import CONF_API_KEY, CONF_ENTSOE_TOKEN, CONF_LATITUDE, CONF_LONGITUDE

TO_REDACT = {CONF_API_KEY, CONF_ENTSOE_TOKEN, CONF_LATITUDE, CONF_LONGITUDE, "latitude", "longitude"}


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: PstrykAIConfigEntry) -> dict[str, Any]:
    c = entry.runtime_data
    data = c.data
    timeline_summary: dict[str, int] = {}
    if data:
        for s in data.timeline.buy:
            timeline_summary[s.source.value] = timeline_summary.get(s.source.value, 0) + 1
    return {
        "entry": {
            "data": async_redact_data(dict(entry.data), TO_REDACT),
            "options": async_redact_data(dict(entry.options), TO_REDACT),
        },
        "pstryk_key_fingerprint": c.pstryk.fingerprint,
        "providers": {k: v.as_dict() for k, v in c.status.items()},
        "pstryk_budget": {"remaining": c.pstryk.budget.remaining(), "requests_this_run": c.pstryk.request_count},
        "price_fields_seen": c.snapshot.price_fields,
        "tomorrow_confirmed": c.snapshot.tomorrow_confirmed,
        "timeline_sources": timeline_summary,
        "controls": c.controls,
        "model": c.model_info(),
        "backtest": c.forecaster.state.backtest,
        "tariff": c.settings.tariff.to_dict(),
        "history_sizes": {
            "market": {k: len(v) for k, v in c.history.market.items()},
            "system": len(c.history.system),
            "weather": len(c.history.weather),
            "snapshots": len(c.history.snapshots),
            "pstryk_prices": len(c.history.pstryk_buy),
        },
        "mqtt": {
            "status": c.publisher.status,
            "prefix": c.publisher.prefix,
            "published": c.publisher.published,
            "skipped": c.publisher.skipped,
        },
        "buffer": data.buffer.to_dict(include_steps=False) if data and data.buffer else None,
    }
