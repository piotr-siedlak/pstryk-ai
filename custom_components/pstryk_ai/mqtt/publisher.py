"""MQTT publication through Home Assistant's configured MQTT integration.

No second broker is required. Publication is skipped (and reported) while
MQTT is not connected; the next refresh republishes the full state, so
reconnects are self-healing. Control-relevant topics (``should_heat``) are
never retained and carry an MQTT v5 expiry so a stale command cannot be
replayed to Loxone after an outage.
"""

from __future__ import annotations

from datetime import datetime
import inspect
import logging

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

from .schemas import Message, resolve_topic

_LOGGER = logging.getLogger(__name__)


class MqttPublisher:
    def __init__(
        self,
        hass: HomeAssistant,
        prefix: str,
        *,
        qos: int = 1,
        retain: bool = True,
        topics: dict[str, str] | None = None,
    ) -> None:
        self.hass = hass
        self.prefix = prefix.strip().strip("/")
        self.qos = qos
        self.retain = retain
        self.topics = dict(topics or {})
        self.sent_topics: set[str] = set()
        self.last_publish: datetime | None = None
        self.last_error: str | None = None
        self.published = 0
        self.skipped = 0

    def topic(self, suffix: str) -> str | None:
        """Full topic for a canonical name (``None`` = disabled by the user)."""
        return resolve_topic(self.prefix, suffix.strip("/"), self.topics)

    def available(self) -> bool:
        if "mqtt" not in self.hass.config.components:
            return False
        try:
            from homeassistant.components import mqtt

            return mqtt.is_connected(self.hass)
        except (KeyError, HomeAssistantError):
            return False

    @property
    def status(self) -> str:
        if "mqtt" not in self.hass.config.components:
            return "not_configured"
        if not self.available():
            return "disconnected"
        if self.last_error:
            return "error"
        return "ok"

    async def async_publish(self, messages: list[Message], now: datetime) -> int:
        if not self.available():
            self.skipped += len(messages)
            self.last_error = "disconnected"
            return 0
        from homeassistant.components import mqtt

        expiry_supported = _supports_expiry(mqtt.async_publish)
        sent = 0
        messages = [m for m in messages if self.topic(m.topic) is not None]
        for msg in messages:
            kwargs: dict = {"qos": self.qos, "retain": msg.retain and self.retain}
            if msg.expiry_s is not None and expiry_supported:
                kwargs["message_expiry_interval"] = msg.expiry_s
            try:
                full = self.topic(msg.topic)
                await mqtt.async_publish(self.hass, full, msg.payload, **kwargs)
                self.sent_topics.add(full)
                sent += 1
            except HomeAssistantError as err:
                self.last_error = str(err)[:120]
                _LOGGER.debug("MQTT publish to %s failed: %s", msg.topic, err)
        if sent == len(messages):
            self.last_error = None
        self.published += sent
        self.last_publish = now
        return sent

    async def async_raw(self, topic: str, payload: str, retain: bool = True) -> None:
        """Publish to an absolute topic (used for discovery)."""
        if not self.available():
            return
        from homeassistant.components import mqtt

        await mqtt.async_publish(self.hass, topic, payload, qos=self.qos, retain=retain)


def _supports_expiry(func: object) -> bool:
    """MQTT v5 message expiry is only available in newer Home Assistant releases."""
    try:
        return "message_expiry_interval" in inspect.signature(func).parameters  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False
