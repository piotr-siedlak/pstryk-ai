"""Notifications (each type can be enabled separately).

Sent through a notify service chosen in the options (e.g.
``notify.mobile_app_telefon``) or, if none is set, as a persistent notification
in Home Assistant. Every notification is also fired as the event
``pstryk_ai_notification`` so automations can react to it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import logging

from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

EVENT_NOTIFICATION = f"{DOMAIN}_notification"

KIND_TOMORROW = "tomorrow_prices"
KIND_NEGATIVE = "negative_prices"
KIND_FALLBACK = "local_control"
KIND_STALE = "stale_data"
KINDS = (KIND_TOMORROW, KIND_NEGATIVE, KIND_FALLBACK, KIND_STALE)


@dataclass
class Notifier:
    hass: HomeAssistant
    enabled: dict[str, bool] = field(default_factory=dict)
    service: str | None = None  # "notify.mobile_app_x"
    sent: dict[str, str] = field(default_factory=dict)  # kind -> dedup key of the last message

    async def async_send(self, kind: str, title: str, message: str, dedup: str | None = None) -> bool:
        if not self.enabled.get(kind):
            return False
        if dedup is not None and self.sent.get(kind) == dedup:
            return False
        self.sent[kind] = dedup or message
        self.hass.bus.async_fire(EVENT_NOTIFICATION, {"kind": kind, "title": title, "message": message})
        try:
            if self.service:
                domain, _, name = self.service.partition(".")
                await self.hass.services.async_call(domain, name, {"title": title, "message": message}, blocking=False)
            else:
                from homeassistant.components import persistent_notification

                persistent_notification.async_create(
                    self.hass, message, title=title, notification_id=f"{DOMAIN}_{kind}"
                )
        except Exception as err:
            _LOGGER.warning("Pstryk AI notification failed: %s", err)
            return False
        return True

    def reset(self, kind: str) -> None:
        self.sent.pop(kind, None)
