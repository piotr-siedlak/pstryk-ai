"""Import Pstryk daily totals into Home Assistant long-term statistics.

External statistics (``pstryk_ai:*``) let you see the full Pstryk history in the
Energy dashboard and statistic graphs, including days before the integration
was installed (as far back as the fetched daily history goes). Each local day
total is stored at the hour of the day's local midnight; ``sum`` is cumulative.
Re-importing is idempotent (rows are upserted by start time).
"""

from __future__ import annotations

from datetime import datetime
import logging
from zoneinfo import ZoneInfo

from homeassistant.core import HomeAssistant

from .const import DOMAIN, LOCAL_TZ
from .spends import PeriodTotals

_LOGGER = logging.getLogger(__name__)
TZ = ZoneInfo(LOCAL_TZ)

STATISTICS = {
    "energy_import": ("Pstryk – pobór energii", "kWh", "energy", "import_kwh"),
    "energy_export": ("Pstryk – oddanie energii", "kWh", "energy", "export_kwh"),
    "import_cost": ("Pstryk – koszt energii", "PLN", None, "cost"),
    "sold_value": ("Pstryk – wartość sprzedanej energii", "PLN", None, "sold"),
}


def statistic_id(key: str) -> str:
    return f"{DOMAIN}:{key}"


def build_rows(days: dict[str, PeriodTotals], attr: str) -> list[dict]:
    rows = []
    total = 0.0
    for key, item in sorted(days.items()):
        value = getattr(item, attr)
        if value is None:
            continue
        d = datetime.fromisoformat(key)
        start = datetime(d.year, d.month, d.day, tzinfo=TZ)
        total += float(value)
        rows.append({"start": start, "state": float(value), "sum": round(total, 4)})
    return rows


async def async_import(hass: HomeAssistant, days: dict[str, PeriodTotals]) -> int:
    """Push daily totals to the recorder. Returns the number of rows written."""
    if "recorder" not in hass.config.components or not days:
        return 0
    from homeassistant.components.recorder.models import StatisticData, StatisticMetaData
    from homeassistant.components.recorder.statistics import async_add_external_statistics

    try:
        from homeassistant.components.recorder.models import StatisticMeanType

        mean_kw = {"mean_type": StatisticMeanType.NONE}
    except ImportError:  # older releases
        mean_kw = {"has_mean": False}

    written = 0
    for key, (name, unit, unit_class, attr) in STATISTICS.items():
        rows = build_rows(days, attr)
        if not rows:
            continue
        metadata = StatisticMetaData(
            has_sum=True,
            name=name,
            source=DOMAIN,
            statistic_id=statistic_id(key),
            unit_class=unit_class,
            unit_of_measurement=unit,
            **mean_kw,  # type: ignore[typeddict-item]
        )
        stats = [StatisticData(start=r["start"], state=r["state"], sum=r["sum"]) for r in rows]
        async_add_external_statistics(hass, metadata, stats)
        written += len(stats)
    return written
