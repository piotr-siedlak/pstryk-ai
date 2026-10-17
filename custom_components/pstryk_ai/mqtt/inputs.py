"""MQTT input readings (e.g. buffer temperature published by Loxone).

Each configured input is an exact topic (no wildcards). Payloads may be a plain
number (``42.5`` / ``42,5``) or JSON; for JSON a key (or dotted path such as
``sensors.buffer``) selects the value, otherwise common keys are tried
(``value``, ``temperature``, ``temp``, ``state``). Readings older than
``max_age`` are treated as missing so stale data never drives a decision.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import json
import logging
from typing import Any

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback

_LOGGER = logging.getLogger(__name__)

DEFAULT_KEYS = ("value", "temperature", "temp", "state", "val")
DEFAULT_MAX_AGE = timedelta(minutes=30)


def parse_number(payload: Any, key: str | None = None) -> float | None:
    """Extract a float from a raw MQTT payload."""
    if isinstance(payload, bytes):
        payload = payload.decode("utf-8", "replace")
    text = str(payload).strip()
    if not text:
        return None
    try:
        return float(text.replace(",", "."))
    except ValueError:
        pass
    try:
        data = json.loads(text)
    except ValueError:
        return None
    if isinstance(data, (int, float)) and not isinstance(data, bool):
        return float(data)
    if not isinstance(data, dict):
        return None
    if key:
        node: Any = data
        for part in key.split("."):
            if not isinstance(node, dict) or part not in node:
                return None
            node = node[part]
        candidates = [node]
    else:
        candidates = [data[k] for k in DEFAULT_KEYS if k in data]
    for value in candidates:
        try:
            return float(str(value).replace(",", "."))
        except (TypeError, ValueError):
            continue
    return None


@dataclass(slots=True)
class InputSpec:
    name: str  # e.g. "buffer", "outdoor", "device:Bojler"
    topic: str
    key: str | None = None
    min_value: float = -60.0
    max_value: float = 150.0


@dataclass(slots=True)
class Reading:
    value: float
    received: datetime
    topic: str


class MqttInputs:
    """Subscribes to the configured input topics and keeps the latest values."""

    def __init__(
        self,
        hass: HomeAssistant,
        specs: list[InputSpec],
        *,
        max_age: timedelta = DEFAULT_MAX_AGE,
        on_update: Callable[[str, float, float | None], None] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.hass = hass
        self.specs = [s for s in specs if s.topic]
        self.max_age = max_age
        self._on_update = on_update
        self._now = now or (lambda: datetime.now(UTC))
        self.readings: dict[str, Reading] = {}
        self.rejected: dict[str, str] = {}
        self._unsubs: list[CALLBACK_TYPE] = []

    async def async_start(self) -> bool:
        if not self.specs:
            return True
        if "mqtt" not in self.hass.config.components:
            _LOGGER.warning("MQTT inputs configured but the MQTT integration is not set up")
            return False
        from homeassistant.components import mqtt

        for spec in self.specs:
            self._unsubs.append(await mqtt.async_subscribe(self.hass, spec.topic, self._handler(spec), qos=1))
        return True

    def _handler(self, spec: InputSpec) -> Callable[[Any], None]:
        @callback
        def _received(msg: Any) -> None:
            value = parse_number(msg.payload, spec.key)
            if value is None or not spec.min_value <= value <= spec.max_value:
                self.rejected[spec.name] = str(msg.payload)[:60]
                _LOGGER.debug("Ignoring MQTT input %s on %s: %r", spec.name, spec.topic, msg.payload)
                return
            previous = self.value(spec.name)
            self.readings[spec.name] = Reading(value, self._now(), spec.topic)
            self.rejected.pop(spec.name, None)
            if self._on_update is not None:
                self._on_update(spec.name, value, previous)

        return _received

    def value(self, name: str) -> float | None:
        reading = self.readings.get(name)
        if reading is None or self._now() - reading.received > self.max_age:
            return None
        return reading.value

    def has(self, name: str) -> bool:
        return any(s.name == name for s in self.specs)

    def status(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for spec in self.specs:
            r = self.readings.get(spec.name)
            out[spec.name] = {
                "topic": spec.topic,
                "key": spec.key,
                "value": None if r is None else r.value,
                "received": None if r is None else r.received.isoformat(),
                "fresh": self.value(spec.name) is not None,
                "rejected_payload": self.rejected.get(spec.name),
            }
        return out

    def stop(self) -> None:
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
