"""Local persistent time-series storage (Home Assistant ``Store`` JSON files).

Files live in ``.storage/pstryk_ai.<entry_id>.<dataset>``. Retention is
enforced on every save. Pstryk customer data is kept only for a short window
(default 14 days) for forecast-vs-actual comparison; nothing is uploaded.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, timedelta
import logging
from typing import Any

from homeassistant.core import HomeAssistant

from ..api.pse import SystemForecastHour
from ..api.weather import WeatherHour
from ..const import DOMAIN
from ..models.forecasts import ForecastRun
from ..models.price_slot import MarketPoint, aggregate_hourly, floor_hour, iso, parse_iso
from .migrations import CURRENT_MAJOR, CURRENT_MINOR, VersionedStore

_LOGGER = logging.getLogger(__name__)

SAVE_DELAY = 30
PSTRYK_RETENTION_DAYS = 14
SNAPSHOT_LIMIT = 120
DECISION_RETENTION_DAYS = 14


def _store(hass: HomeAssistant, entry_id: str, name: str) -> VersionedStore:
    return VersionedStore(hass, CURRENT_MAJOR, f"{DOMAIN}.{entry_id}.{name}", minor_version=CURRENT_MINOR)


class HistoryStore:
    """In-memory datasets backed by HA storage."""

    def __init__(self, hass: HomeAssistant, entry_id: str, history_days: int = 400) -> None:
        self.hass = hass
        self.history_days = history_days
        self._stores = {
            name: _store(hass, entry_id, name) for name in ("market", "system", "weather", "forecasts", "state")
        }
        # provider -> hour -> PLN/MWh
        self.market: dict[str, dict[datetime, float]] = {}
        # recent native-resolution points (15-min) for display, per provider
        self.market_native: dict[str, list[MarketPoint]] = {}
        self.system: dict[datetime, SystemForecastHour] = {}
        self.weather: dict[datetime, WeatherHour] = {}
        self.snapshots: list[ForecastRun] = []
        self.live_errors: dict[str, list[float]] = {}  # horizon day -> abs errors
        self.state: dict[str, Any] = {}
        self.pstryk_buy: dict[datetime, float] = {}
        self.decisions: list[dict[str, Any]] = []
        self.loaded = False

    # --------------------------------------------------------------- load
    async def async_load(self) -> None:
        market = await self._stores["market"].async_load() or {}
        for provider, series in (market.get("hourly") or {}).items():
            self.market[provider] = {parse_iso(k): float(v) for k, v in series.items()}
        for provider, items in (market.get("native") or {}).items():
            self.market_native[provider] = [MarketPoint.from_dict(i) for i in items]

        system = await self._stores["system"].async_load() or {}
        for item in system.get("hours") or []:
            row = SystemForecastHour.from_dict(item)
            self.system[row.start] = row

        weather = await self._stores["weather"].async_load() or {}
        for item in weather.get("hours") or []:
            row = WeatherHour.from_dict(item)
            self.weather[row.start] = row

        forecasts = await self._stores["forecasts"].async_load() or {}
        self.snapshots = [ForecastRun.from_dict(s) for s in forecasts.get("snapshots") or []]
        self.live_errors = {k: list(v) for k, v in (forecasts.get("live_errors") or {}).items()}

        state = await self._stores["state"].async_load() or {}
        self.state = state.get("state") or {}
        self.pstryk_buy = {parse_iso(k): float(v) for k, v in (state.get("pstryk_buy") or {}).items()}
        self.decisions = state.get("decisions") or []
        self.loaded = True

    # --------------------------------------------------------------- mutate
    def add_market(self, points: Iterable[MarketPoint]) -> int:
        points = list(points)
        added = 0
        by_provider: dict[str, list[MarketPoint]] = {}
        for p in points:
            by_provider.setdefault(p.provider, []).append(p)
        for provider, items in by_provider.items():
            hourly = aggregate_hourly(items)
            series = self.market.setdefault(provider, {})
            for hour, value in hourly.items():
                if series.get(hour) != value:
                    added += 1
                series[hour] = value
            native = [p for p in items if p.product == "quarter_hour"]
            if native:
                keep = {p.start: p for p in self.market_native.get(provider, [])}
                keep.update({p.start: p for p in native})
                cutoff = datetime.now(UTC) - timedelta(days=3)
                self.market_native[provider] = sorted(
                    (p for p in keep.values() if p.start >= cutoff), key=lambda p: p.start
                )
        return added

    def add_system(self, rows: Iterable[SystemForecastHour]) -> None:
        for row in rows:
            self.system[row.start] = row

    def add_weather(self, rows: Iterable[WeatherHour]) -> None:
        for row in rows:
            self.weather[row.start] = row

    def add_snapshot(self, run: ForecastRun) -> None:
        self.snapshots.append(run)
        self.snapshots = self.snapshots[-SNAPSHOT_LIMIT:]

    def add_pstryk_prices(self, prices: dict[datetime, float]) -> None:
        self.pstryk_buy.update(prices)

    def add_decision(self, decision: dict[str, Any]) -> None:
        self.decisions.append(decision)

    def evaluate_snapshots(self, actual: dict[datetime, float], day_of: Callable[[datetime], date]) -> int:
        """Compare stored snapshots with newly known actual market prices.

        Returns the number of evaluated points. Each point is evaluated once.
        """
        evaluated = 0
        for run in self.snapshots:
            for p in run.points:
                if p.quality_status == "evaluated" or p.forecast_for not in actual:
                    continue
                day = max(1, (day_of(p.forecast_for) - day_of(run.created_at)).days)
                self.live_errors.setdefault(str(min(day, 7)), []).append(abs(actual[p.forecast_for] - p.prediction_p50))
                p.quality_status = "evaluated"
                evaluated += 1
        for k, values in self.live_errors.items():
            self.live_errors[k] = values[-24 * 30 :]
        return evaluated

    def live_mae(self) -> dict[str, float]:
        return {k: round(sum(v) / len(v), 2) for k, v in sorted(self.live_errors.items()) if v}

    # -------------------------------------------------------------- queries
    def market_series(self, provider: str) -> dict[datetime, float]:
        return self.market.get(provider, {})

    def latest_market_hour(self, provider: str) -> datetime | None:
        series = self.market.get(provider)
        return max(series) if series else None

    # ---------------------------------------------------------------- save
    def _prune(self) -> None:
        now = datetime.now(UTC)
        cutoff = floor_hour(now) - timedelta(days=self.history_days)
        for provider, series in self.market.items():
            self.market[provider] = {h: v for h, v in series.items() if h >= cutoff}
        self.system = {h: v for h, v in self.system.items() if h >= cutoff}
        self.weather = {h: v for h, v in self.weather.items() if h >= cutoff}
        p_cut = now - timedelta(days=PSTRYK_RETENTION_DAYS)
        self.pstryk_buy = {h: v for h, v in self.pstryk_buy.items() if h >= p_cut}
        d_cut = iso(now - timedelta(days=DECISION_RETENTION_DAYS)) or ""
        self.decisions = [d for d in self.decisions if (d.get("at") or "") >= d_cut][-2000:]

    def _data(self, name: str) -> dict[str, Any]:
        if name == "market":
            return {
                "hourly": {
                    provider: {iso(h): round(v, 3) for h, v in sorted(series.items())}
                    for provider, series in self.market.items()
                },
                "native": {p: [i.to_dict() for i in items] for p, items in self.market_native.items()},
            }
        if name == "system":
            return {"hours": [r.to_dict() for _, r in sorted(self.system.items())]}
        if name == "weather":
            return {"hours": [r.to_dict() for _, r in sorted(self.weather.items())]}
        if name == "forecasts":
            return {"snapshots": [s.to_dict() for s in self.snapshots], "live_errors": self.live_errors}
        return {
            "state": self.state,
            "pstryk_buy": {iso(h): v for h, v in sorted(self.pstryk_buy.items())},
            "decisions": self.decisions,
        }

    def schedule_save(self, *names: str) -> None:
        self._prune()
        for name in names or tuple(self._stores):
            self._stores[name].async_delay_save(lambda n=name: self._data(n), SAVE_DELAY)

    async def async_save_now(self) -> None:
        self._prune()
        for name, store in self._stores.items():
            await store.async_save(self._data(name))

    async def async_remove(self) -> None:
        for store in self._stores.values():
            await store.async_remove()
