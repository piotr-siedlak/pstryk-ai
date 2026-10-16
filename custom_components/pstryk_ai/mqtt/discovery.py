"""Optional Home Assistant MQTT Discovery for a *small* set of key topics.

Native HA entities already exist; discovery is meant for other HA instances
or for users who prefer MQTT entities. Time series stay JSON topics and are
deliberately not turned into hundreds of entities.
"""

from __future__ import annotations

import json
from typing import Any

from ..const import VERSION

DISCOVERY_PREFIX = "homeassistant"

ITEMS: list[dict[str, Any]] = [
    {
        "key": "price_current",
        "component": "sensor",
        "topic": "prices/current",
        "name": "Aktualna cena zakupu (MQTT)",
        "unit": "PLN/kWh",
    },
    {
        "key": "price_next",
        "component": "sensor",
        "topic": "prices/next",
        "name": "Cena w następnej godzinie (MQTT)",
        "unit": "PLN/kWh",
    },
    {"key": "cheap_now", "component": "binary_sensor", "topic": "cheap/now", "name": "Tania energia teraz (MQTT)"},
    {
        "key": "buffer_should_heat",
        "component": "binary_sensor",
        "topic": "optimizer/buffer/should_heat",
        "name": "Zalecane grzanie bufora (MQTT)",
    },
    {
        "key": "buffer_target",
        "component": "sensor",
        "topic": "optimizer/buffer/target_temperature",
        "name": "Zalecana temperatura bufora (MQTT)",
        "unit": "°C",
        "device_class": "temperature",
    },
    {
        "key": "forecast_confidence",
        "component": "sensor",
        "topic": "forecast/confidence",
        "name": "Pewność prognozy (MQTT)",
        "unit": "%",
    },
]


def discovery_messages(prefix: str, entry_id: str) -> list[tuple[str, str]]:
    node = f"pstryk_ai_{entry_id[:8]}"
    device = {
        "identifiers": [node],
        "name": "Pstryk AI (MQTT)",
        "manufacturer": "Pstryk AI (community)",
        "sw_version": VERSION,
    }
    out = []
    for item in ITEMS:
        cfg: dict[str, Any] = {
            "name": item["name"],
            "unique_id": f"{node}_{item['key']}",
            "state_topic": f"{prefix}/{item['topic']}",
            "availability_topic": f"{prefix}/availability",
            "device": device,
        }
        if item["component"] == "binary_sensor":
            cfg["payload_on"] = "1"
            cfg["payload_off"] = "0"
        if item.get("unit"):
            cfg["unit_of_measurement"] = item["unit"]
        if item.get("device_class"):
            cfg["device_class"] = item["device_class"]
        if item["key"] == "forecast_confidence":
            cfg["value_template"] = "{{ (value | float(0) * 100) | round(0) }}"
        out.append((f"{DISCOVERY_PREFIX}/{item['component']}/{node}/{item['key']}/config", json.dumps(cfg)))
    return out


def removal_messages(entry_id: str) -> list[tuple[str, str]]:
    node = f"pstryk_ai_{entry_id[:8]}"
    return [(f"{DISCOVERY_PREFIX}/{i['component']}/{node}/{i['key']}/config", "") for i in ITEMS]
