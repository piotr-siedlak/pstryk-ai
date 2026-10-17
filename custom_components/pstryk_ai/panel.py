"""Sidebar panel ("Pstryk AI" dashboard) registration."""

from __future__ import annotations

import logging
from pathlib import Path

from homeassistant.core import HomeAssistant

from .const import DOMAIN, VERSION

_LOGGER = logging.getLogger(__name__)

PANEL_URL_PATH = "pstryk-ai"
STATIC_URL = "/pstryk_ai_static"
WEBCOMPONENT = "pstryk-ai-panel"
FRONTEND_DIR = Path(__file__).parent / "frontend"
DATA_PANEL = f"{DOMAIN}_panel"
DATA_STATIC = f"{DOMAIN}_static_registered"


async def async_register_panel(hass: HomeAssistant) -> bool:
    """Register the static JS and the sidebar panel once per Home Assistant instance."""
    if hass.data.get(DATA_PANEL):
        return True
    if "http" not in hass.config.components or "frontend" not in hass.config.components:
        _LOGGER.debug("Frontend not loaded; Pstryk AI panel not registered")
        return False
    from homeassistant.components import panel_custom
    from homeassistant.components.http import StaticPathConfig

    if not hass.data.get(DATA_STATIC):
        await hass.http.async_register_static_paths(
            [StaticPathConfig(STATIC_URL, str(FRONTEND_DIR), cache_headers=False)]
        )
        hass.data[DATA_STATIC] = True
    await panel_custom.async_register_panel(
        hass,
        frontend_url_path=PANEL_URL_PATH,
        webcomponent_name=WEBCOMPONENT,
        sidebar_title="Pstryk AI",
        sidebar_icon="mdi:flash",
        module_url=f"{STATIC_URL}/{WEBCOMPONENT}.js?v={VERSION}",
        require_admin=False,
        config={},
    )
    hass.data[DATA_PANEL] = True
    return True


def async_unregister_panel(hass: HomeAssistant) -> None:
    if not hass.data.pop(DATA_PANEL, False):
        return
    from homeassistant.components import frontend

    frontend.async_remove_panel(hass, PANEL_URL_PATH, warn_if_unknown=False)
