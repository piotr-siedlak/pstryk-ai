"""Storage schema migrations."""

from __future__ import annotations

from typing import Any

from homeassistant.helpers.storage import Store

CURRENT_MAJOR = 1
CURRENT_MINOR = 1


class VersionedStore(Store[dict[str, Any]]):
    """Store with an explicit migration hook."""

    async def _async_migrate_func(
        self, old_major_version: int, old_minor_version: int, old_data: dict[str, Any]
    ) -> dict[str, Any]:
        data = dict(old_data or {})
        if old_major_version > CURRENT_MAJOR:
            # Data written by a newer version: start fresh rather than misread it.
            return {}
        # 1.0 -> 1.1: add schema marker
        data.setdefault("schema", f"{CURRENT_MAJOR}.{CURRENT_MINOR}")
        return data
