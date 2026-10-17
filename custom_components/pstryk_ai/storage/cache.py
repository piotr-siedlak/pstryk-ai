"""Last-known-good provider responses (restart and outage recovery).

The Pstryk hourly response is cached so that confirmed prices survive Home
Assistant restarts and API outages without spending request budget. The
request-budget state is persisted too, so a restart cannot reset the hourly
counter and accidentally exceed the provider limit.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.core import HomeAssistant

from ..const import DOMAIN
from ..models.price_slot import iso, parse_iso
from .migrations import CURRENT_MAJOR, CURRENT_MINOR, VersionedStore


class ProviderCache:
    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        self._store = VersionedStore(hass, CURRENT_MAJOR, f"{DOMAIN}.{entry_id}.cache", minor_version=CURRENT_MINOR)
        self._data: dict[str, Any] = {}

    async def async_load(self) -> None:
        self._data = await self._store.async_load() or {}

    def get(self, key: str) -> tuple[Any, datetime | None]:
        item = self._data.get(key)
        if not item:
            return None, None
        at = parse_iso(item["at"]) if item.get("at") else None
        return item.get("payload"), at

    def put(self, key: str, payload: Any, at: datetime) -> None:
        self._data[key] = {"payload": payload, "at": iso(at)}
        self._store.async_delay_save(lambda: self._data, 10)

    def budget_state(self, fingerprint: str) -> dict[str, Any]:
        return (self._data.get("budgets") or {}).get(fingerprint) or {}

    def put_budget_state(self, fingerprint: str, state: dict[str, Any]) -> None:
        self._data.setdefault("budgets", {})[fingerprint] = state
        self._store.async_delay_save(lambda: self._data, 10)

    async def async_flush(self) -> None:
        await self._store.async_save(self._data)

    async def async_remove(self) -> None:
        await self._store.async_remove()
