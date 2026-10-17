"""Shared fixtures."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
import math
from pathlib import Path
import random
from typing import Any
from zoneinfo import ZoneInfo

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
TZ = ZoneInfo("Europe/Warsaw")


def load_fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def load_json(name: str) -> Any:
    return json.loads(load_fixture(name))


def local_midnight_utc(year: int, month: int, day: int) -> datetime:
    return datetime(year, month, day, tzinfo=TZ).astimezone(UTC)


def pstryk_frames(
    day_start_utc: datetime,
    hours: int,
    *,
    price: float | None = None,
    base: float = 0.55,
    sell: bool = True,
    meter: bool = True,
    live_index: int | None = None,
    step: timedelta = timedelta(hours=1),
) -> list[dict[str, Any]]:
    """Frames shaped like the unified-metrics response (fields per API docs)."""
    frames = []
    scale = step / timedelta(hours=1)
    for i in range(hours):
        start = day_start_utc + step * i
        value = price if price is not None else round(base + 0.25 * math.sin(i / 24 * 2 * math.pi), 4)
        pricing = {
            "price_gross": value,
            "price_net": round(value / 1.23, 4),
            "is_cheap": value < base - 0.1,
            "is_expensive": value > base + 0.1,
        }
        if sell:
            pricing["price_prosumer_gross"] = round(max(value - 0.1, 0) * 0.9, 4)
        metrics: dict[str, Any] = {"pricing": pricing}
        if meter:
            metrics["meterValues"] = {
                "energy_active_import_register": round(0.8 * scale, 3),
                "energy_active_export_register": round(0.1 * scale, 3),
                "energy_balance": round(0.7 * scale, 3),
            }
            metrics["cost"] = {
                "energy_import_cost": round(0.8 * value * scale, 4),
                "energy_sold_value": round(0.03 * scale, 4),
                "energy_balance_value": round((0.03 - 0.8 * value) * scale, 4),
                "energy_cost_net": round(0.5 * value * scale, 4),
                "var_dist_cost_net": round(0.2 * scale, 4),
                "vat": round(0.05 * scale, 4),
            }
        frame = {
            "start": start.isoformat().replace("+00:00", "Z"),
            "end": (start + step).isoformat().replace("+00:00", "Z"),
            "metrics": metrics,
        }
        if live_index == i:
            frame["is_live"] = True
        frames.append(frame)
    return frames


def pstryk_payload(frames: list[dict[str, Any]]) -> dict[str, Any]:
    return {"frames": frames, "summary": {"meterValues": {}, "cost": {}}}


def synthetic_market(start: datetime, hours: int, seed: int = 3) -> dict[datetime, float]:
    rnd = random.Random(seed)
    out = {}
    for i in range(hours):
        t = start + timedelta(hours=i)
        local = t.astimezone(TZ)
        h = local.hour
        weekday = local.weekday() < 5
        out[t] = 420 + 160 * math.sin((h - 7) / 24 * 2 * math.pi) + (70 if weekday else -50) + rnd.gauss(0, 35)
    return out


@pytest.fixture(autouse=True)
def _frozen_clock(request: pytest.FixtureRequest) -> None:
    """Run every test at a fixed afternoon time (14:30 Europe/Warsaw).

    Behaviour depends on the time of day (e.g. tomorrow's prices are only
    fetched after noon), so tests must not depend on when CI runs.
    Override with PSTRYK_TEST_NOW=<ISO time> to explore other times.
    """
    import os

    freezer = request.getfixturevalue("freezer")
    freezer.move_to(os.environ.get("PSTRYK_TEST_NOW", "2026-10-16T12:30:00Z"))


@pytest.fixture
def market_history() -> dict[datetime, float]:
    return synthetic_market(datetime(2025, 9, 1, tzinfo=UTC), 24 * 410)
