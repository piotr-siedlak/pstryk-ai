"""The shipped dashboard templates render against real integration state."""

from __future__ import annotations

from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.helpers.template import Template
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker
import yaml

from custom_components.pstryk_ai.api import pstryk as pstryk_api

from .test_init import PSTRYK_URL, PstrykMock, _entry, _mock_public_apis, _setup

DASHBOARD = Path(__file__).parents[1] / "dashboards" / "pstryk_ai.yaml"


@pytest.fixture(autouse=True)
def _auto(enable_custom_integrations: None) -> None:
    pstryk_api._BUDGETS.clear()


def _cards(node):
    if isinstance(node, dict):
        if node.get("type") == "markdown":
            yield node
        for v in node.values():
            yield from _cards(v)
    elif isinstance(node, list):
        for v in node:
            yield from _cards(v)


async def test_dashboard_templates_render(hass: HomeAssistant, aioclient_mock: AiohttpClientMocker) -> None:
    await hass.config.async_set_time_zone("Europe/Warsaw")
    aioclient_mock.get(PSTRYK_URL, side_effect=PstrykMock())
    _mock_public_apis(aioclient_mock)
    hass.states.async_set("sensor.bufor", "41")
    entry = _entry(mqtt_enabled=False)
    await _setup(hass, entry)
    config = yaml.safe_load(DASHBOARD.read_text(encoding="utf-8"))
    cards = list(_cards(config))
    assert len(cards) == 3
    for card in cards:
        rendered = Template(card["content"], hass).async_render(parse_result=False)
        assert "Brak prognozy" not in rendered, card["title"]
        rows = [line for line in rendered.splitlines() if line.startswith("| ") and "---" not in line]
        assert len(rows) >= 3, (card["title"], rendered[:300])
        assert all(row.count("|") == rows[0].count("|") for row in rows), card["title"]
    # every entity referenced by the dashboard exists
    text = DASHBOARD.read_text(encoding="utf-8")
    import re

    for entity_id in set(re.findall(r"\b(?:sensor|binary_sensor|switch|number|select|button)\.pstryk_ai_\w+", text)):
        assert hass.states.get(entity_id) is not None, entity_id
    assert await hass.config_entries.async_unload(entry.entry_id)
