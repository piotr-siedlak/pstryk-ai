"""Central coordinator: data sources, event-aware scheduler, forecast, optimisation."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
import logging
from typing import Any
from zoneinfo import ZoneInfo

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_call_later, async_track_time_change, async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .api.base import ProviderAuthError, ProviderError, ProviderRateLimited
from .api.entsoe import EntsoeClient
from .api.pse import PseClient
from .api.pstryk import PstrykClient, local_day_bounds, parse_daily, parse_hourly
from .api.tge import TgeClient
from .api.weather import WeatherClient, WeatherHour
from .const import (
    DOMAIN,
    EVENT_PLAN_UPDATED,
    EVENT_PRICES_CONFIRMED,
    LOCAL_TZ,
    MARKET_PROVIDER_ENTSOE,
    MARKET_PROVIDER_PSE_RCE,
    MARKET_PROVIDER_TGE,
)
from .forecasting.features import FeatureContext, local_date
from .forecasting.model_manager import ModelState, PriceForecaster
from .heat_runtime import HeatRuntimeMixin, new_learning_store
from .models.energy_data import MeterFrame, PstrykSnapshot
from .models.forecasts import ForecastRun
from .models.price_slot import PriceSlot, floor_hour, iso
from .mqtt.discovery import discovery_messages, removal_messages
from .mqtt.inputs import InputSpec, MqttInputs
from .mqtt.publisher import MqttPublisher
from .mqtt.schemas import TOPICS, Message
from .notify import Notifier
from .optimization.scheduler import schedule_device
from .outputs import PstrykAIData, build_messages, compute_windows, spend_messages
from .settings import Settings, load_settings
from .spends import daily_totals, monthly_totals, summarize
from .statistics import async_import as async_import_statistics
from .storage.cache import ProviderCache
from .storage.history import HistoryStore
from .tariff import calibration_pairs
from .timeline import Timeline, build_timeline

_LOGGER = logging.getLogger(__name__)

STALE_AFTER = timedelta(hours=2)
CONTROL_KEYS = (
    "optimization_enabled",
    "buffer_enabled",
    "mqtt_enabled",
    "advisory_mode",
    "buffer_min_t",
    "buffer_max_t",
    "price_threshold",
    "cheap_hours",
    "forecast_model",
    "buffer_strategy",
    "dhw_enabled",
    "buffer_heater_enabled",
    "dhw_heater_enabled",
    "pv_enabled",
    "power_limit_enabled",
    "optimize_all_in",
    "heat_pump_strategy",
)


class ProviderStatus:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.status = "pending" if enabled else "disabled"
        self.last_success: datetime | None = None
        self.last_attempt: datetime | None = None
        self.last_error: str | None = None
        self.retry_at: datetime | None = None

    def ok(self, now: datetime) -> None:
        self.status, self.last_success, self.last_attempt, self.last_error = "ok", now, now, None

    def fail(self, now: datetime, err: Exception) -> None:
        self.last_attempt = now
        self.last_error = type(err).__name__ if not isinstance(err, ProviderError) else str(err)[:120]
        if isinstance(err, ProviderAuthError):
            self.status = "auth_error"
        elif isinstance(err, ProviderRateLimited):
            self.status = "rate_limited"
            if err.retry_after:
                self.retry_at = now + timedelta(seconds=err.retry_after)
        else:
            self.status = "error"

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "last_success": iso(self.last_success),
            "last_attempt": iso(self.last_attempt),
            "last_error": self.last_error,
            "retry_at": iso(self.retry_at),
        }


class PstrykAICoordinator(HeatRuntimeMixin, DataUpdateCoordinator[PstrykAIData]):
    """Owns all state for one config entry."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, *, now: Callable[[], datetime] | None = None) -> None:
        super().__init__(hass, _LOGGER, name=DOMAIN, config_entry=entry, update_interval=None)
        self.settings: Settings = load_settings(hass, entry)
        self._now = now or dt_util.utcnow
        session = async_get_clientsession(hass)
        s = self.settings
        self.pstryk = PstrykClient(session, s.api_key)
        self.entsoe = EntsoeClient(session, s.entsoe_token, s.eur_pln) if s.entsoe_token else None
        self.pse = PseClient(session)
        self.tge = TgeClient(session) if s.tge_enabled or s.market_provider == MARKET_PROVIDER_TGE else None
        self.weather = WeatherClient(session, s.weather_model)
        self.history = HistoryStore(hass, entry.entry_id, s.history_days + 35)
        self.cache = ProviderCache(hass, entry.entry_id)
        self.forecaster = PriceForecaster(mode=s.forecast_model)
        self.publisher = MqttPublisher(hass, s.mqtt_prefix, qos=s.mqtt_qos, retain=s.mqtt_retain, topics=s.mqtt_topics)
        self.status: dict[str, ProviderStatus] = {
            "pstryk": ProviderStatus(),
            "entsoe": ProviderStatus(self.entsoe is not None),
            "pse": ProviderStatus(s.pse_enabled),
            "tge": ProviderStatus(self.tge is not None),
            "weather": ProviderStatus(),
            "mqtt": ProviderStatus(s.mqtt_enabled),
        }
        self.controls: dict[str, Any] = {
            "optimization_enabled": s.optimization_enabled,
            "buffer_enabled": s.buffer_enabled,
            "mqtt_enabled": s.mqtt_enabled,
            "advisory_mode": s.advisory_mode,
            "buffer_min_t": s.buffer.min_t,
            "buffer_max_t": s.buffer.max_t,
            "price_threshold": s.price_threshold,
            "cheap_hours": s.cheap_hours,
            "forecast_model": s.forecast_model,
            "buffer_strategy": s.buffer_strategy,
            "dhw_enabled": s.ext.dhw.enabled,
            "buffer_heater_enabled": s.ext.buffer_heater.enabled,
            "dhw_heater_enabled": s.ext.dhw_heater.enabled,
            "pv_enabled": s.ext.pv_enabled,
            "power_limit_enabled": s.ext.power_limit_enabled,
            "optimize_all_in": s.ext.optimize_all_in,
            "heat_pump_strategy": s.ext.hp_strategy,
        }
        self.snapshot: PstrykSnapshot = PstrykSnapshot()
        self.daily: list[MeterFrame] = []
        self.monthly_summary: dict[str, Any] = {}
        self.local_weather: list[WeatherHour] = []
        self.national_weather: list[WeatherHour] = []
        self.forecast_run: ForecastRun | None = None
        self._unsubs: list[CALLBACK_TYPE] = []
        self._lock = asyncio.Lock()
        self._training = False
        self._import_task: asyncio.Task | None = None
        self.last_recalc: datetime | None = None
        self.last_main_calc: datetime | None = None
        self.import_status: dict[str, Any] = {"state": "idle"}
        self._prices_just_confirmed = False
        self._discovery_sent = False
        self._stale_checked = False
        self._last_input_recalc: datetime | None = None
        self._pending_input_recalc: CALLBACK_TYPE | None = None
        self._tz = ZoneInfo(LOCAL_TZ)
        self._power_last: tuple[datetime, dict[str, float | None]] | None = None
        self._learn_prev: dict[str, Any] | None = None
        self._last_timeline = None
        self.heat_plan = None
        self.learning = new_learning_store(None)
        self.notifier = Notifier(hass, enabled=dict(s.ext.notify), service=s.ext.notify_service)
        self.inputs = MqttInputs(hass, [])

    # ================================================================ setup
    async def async_initialize(self) -> None:
        await self.history.async_load()
        await self.cache.async_load()
        budget_state = self.cache.budget_state(self.pstryk.fingerprint)
        if budget_state:
            self.pstryk.budget.restore(budget_state)
        persisted = self.history.state.get("controls") or {}
        for key in CONTROL_KEYS:
            if key in persisted:
                self.controls[key] = persisted[key]
        # a feature switched off in the options cannot be switched on at runtime
        x = self.settings.ext
        for key, allowed in (
            ("dhw_enabled", x.dhw.enabled),
            ("buffer_heater_enabled", x.buffer_heater.enabled),
            ("dhw_heater_enabled", x.dhw_heater.enabled),
            ("pv_enabled", x.pv_enabled),
            ("power_limit_enabled", x.power_limit_enabled),
        ):
            if not allowed:
                self.controls[key] = False
        self.forecaster.mode = self.controls["forecast_model"]
        self.learning = new_learning_store(self.history.state.get("learning"))
        if model := self.history.state.get("model"):
            self.forecaster.state = ModelState.from_dict(model)
        # restore the last good Pstryk payload: confirmed prices survive restarts
        raw, at = self.cache.get("pstryk_hourly")
        if raw and at:
            try:
                self.snapshot = parse_hourly(raw, self._now())
                self.snapshot.fetched_at = at
            except ProviderError:
                _LOGGER.debug("Cached Pstryk payload unusable")
        raw_daily, _ = self.cache.get("pstryk_daily")
        if raw_daily:
            frames, self.monthly_summary = parse_daily(raw_daily)
            self._apply_daily_frames(frames)
        for key, target in (("weather_local", "local_weather"), ("weather_national", "national_weather")):
            payload, _ = self.cache.get(key)
            if payload:
                setattr(self, target, [WeatherHour.from_dict(i) for i in payload])

    def async_start_schedule(self) -> None:
        """Register the event-aware schedule (all times local, Europe/Warsaw)."""
        track = self._track
        track(self._on_slot_boundary, minute=0, second=5)
        track(self._on_hourly_pstryk, minute=2, second=0)
        track(self._on_extra_pstryk, minute=32, second=0)
        track(self._on_rollover, hour=0, minute=5, second=0)
        track(self._on_weather, hour=6, minute=0, second=30)
        track(self._on_weather, hour=18, minute=0, second=30)
        if self.settings.weather_refresh_h and self.settings.weather_refresh_h < 12:
            hours = [h for h in range(24) if h % self.settings.weather_refresh_h == 3]
            for h in hours:
                track(self._on_weather, hour=h, minute=10, second=0)
        track(self._on_fixing_one, hour=10, minute=45, second=0)
        track(self._on_main_calculation, hour=13, minute=0, second=0)
        track(self._on_fixing_two, hour=14, minute=5, second=0)
        for h in (1, 7, 11, 19, 22):
            track(self._on_daily_balance, hour=h, minute=17, second=0)
        track(self._on_retrain_check, hour=3, minute=30, second=0)
        track(self._on_spare_budget, minute=47, second=0)
        if self.settings.ext.heartbeat:

            @callback
            def _beat(_now: datetime) -> None:
                if self.controls["mqtt_enabled"]:
                    self.config_entry.async_create_background_task(
                        self.hass,
                        self.publisher.async_publish(
                            [Message("heartbeat", iso(self._now()) or "", retain=False, expiry_s=180)], self._now()
                        ),
                        f"{DOMAIN}_heartbeat",
                    )

            self._unsubs.append(async_track_time_interval(self.hass, _beat, timedelta(seconds=60)))

    def _track(self, action: Callable[[], Any], **kwargs: int) -> None:
        @callback
        def _fire(_now: datetime) -> None:
            self.config_entry.async_create_background_task(self.hass, action(), f"{DOMAIN}_{action.__name__}")

        # async_track_time_change uses local time of the HA instance; Europe/Warsaw expected.
        self._unsubs.append(async_track_time_change(self.hass, _fire, **kwargs))

    async def async_shutdown(self) -> None:
        self.inputs.stop()
        if self._pending_input_recalc is not None:
            self._pending_input_recalc()
            self._pending_input_recalc = None
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
        if self._import_task and not self._import_task.done():
            self._import_task.cancel()
        if self.controls.get("mqtt_enabled"):
            from .mqtt.schemas import Message

            await self.publisher.async_publish([Message("availability", "offline")], self._now())
        await self.history.async_save_now()
        await self.cache.async_flush()
        await super().async_shutdown()

    # ============================================================ triggers
    async def _on_slot_boundary(self) -> None:
        # price-slot change: recompute from local state, no external API call
        now = self._now()
        self.integrate_power(now)
        self.learning_tick(now, self.heat_plan)
        await self.async_recalculate(reason="slot_boundary", forecast=False)

    async def _on_hourly_pstryk(self) -> None:
        await self.async_refresh_pstryk()
        await self.async_recalculate(reason="pstryk_hourly", forecast=False)

    async def _on_extra_pstryk(self) -> None:
        local = dt_util.as_local(self._now())
        if 13 <= local.hour <= 17 and not self.snapshot.tomorrow_confirmed:
            await self.async_refresh_pstryk(prices_only=True)
            await self.async_recalculate(reason="pstryk_tomorrow_retry", forecast=False)

    async def _on_rollover(self) -> None:
        await self.async_refresh_market()
        await self.async_recalculate(reason="rollover", forecast=True)

    async def _on_weather(self) -> None:
        await asyncio.gather(self.async_refresh_weather(), self.async_refresh_pse())
        await self.async_recalculate(reason="weather", forecast=True)

    async def _on_fixing_one(self) -> None:
        await self.async_refresh_market()
        await self.async_recalculate(reason="tge_fixing_1", forecast=True)

    async def _on_main_calculation(self) -> None:
        await asyncio.gather(self.async_refresh_market(), self.async_refresh_pse())
        await self.async_recalculate(reason="daily_13", forecast=True, snapshot=True)
        self.last_main_calc = self._now()

    async def _on_fixing_two(self) -> None:
        await self.async_refresh_market()
        await self.async_recalculate(reason="tge_fixing_2", forecast=True)

    async def _on_daily_balance(self) -> None:
        local = dt_util.as_local(self._now())
        if 13 <= local.hour <= 17 and not self.snapshot.tomorrow_confirmed:
            return  # keep budget free for tomorrow's prices
        await self.async_refresh_pstryk_daily()

    async def _on_retrain_check(self) -> None:
        if not self.settings.auto_retrain:
            return
        trained = self.forecaster.state.trained_at
        if trained is None or self._now() - datetime.fromisoformat(trained) > timedelta(days=7):
            await self.async_retrain()

    # ======================================================= DataUpdate
    async def _async_update_data(self) -> PstrykAIData:
        """Initial refresh: fetch every source once, then compute."""
        await asyncio.gather(
            self.async_refresh_pstryk(raise_auth=True),
            self.async_refresh_market(),
            self.async_refresh_pse(),
            self.async_refresh_weather(),
            return_exceptions=False,
        )
        if not self.daily:
            # first start: no cached daily/monthly balance yet (uses the 2nd request of the hourly budget)
            await self.async_refresh_pstryk_daily()
        return await self._compute(reason="startup", forecast=True)

    # ===================================================== Pstryk refresh
    async def async_refresh_pstryk(self, *, prices_only: bool = False, raise_auth: bool = False) -> None:
        now = self._now()
        st = self.status["pstryk"]
        today_start, today_end = local_day_bounds(now)
        tomorrow_end = local_day_bounds(today_end + timedelta(hours=1))[1]
        local = dt_util.as_local(now)
        have_today = self._has_complete_day(self.snapshot.buy, today_start, today_end)
        need_pricing = (not have_today) or (local.hour >= 12 and not self.snapshot.tomorrow_confirmed)
        if prices_only and not need_pricing:
            return
        metrics = ["meter_values", "cost"] if not prices_only else []
        if need_pricing:
            metrics.append("pricing")
        if not metrics:
            return
        window_end = tomorrow_end if need_pricing else floor_hour(now) + timedelta(hours=1)
        try:
            raw = await self.pstryk.fetch_hourly(today_start, window_end, metrics)
        except ProviderAuthError as err:
            st.fail(now, err)
            self._raise_issue("pstryk_auth", "pstryk_auth_failed")
            if raise_auth:
                raise ConfigEntryAuthFailed("Pstryk API key rejected") from err
            return
        except ProviderError as err:
            st.fail(now, err)
            _LOGGER.info("Pstryk refresh skipped: %s", err)
            return
        finally:
            self.cache.put_budget_state(self.pstryk.fingerprint, self.pstryk.budget.export())
        st.ok(now)
        self._clear_issue("pstryk_auth")
        new = parse_hourly(raw, now)
        was_confirmed = self.snapshot.tomorrow_confirmed and self._same_day(self.snapshot.fetched_at, now)
        self.snapshot = self._merge_snapshot(self.snapshot, new, now)
        if need_pricing:
            # only responses with pricing are cached: they restore confirmed prices after restart
            self.cache.put("pstryk_hourly", raw, now)
        confirmed = {floor_hour(s.start): s.value for s in self.snapshot.buy if s.value is not None}
        self.history.add_pstryk_prices(confirmed)
        self.history.schedule_save("state")
        if self.snapshot.tomorrow_confirmed and not was_confirmed:
            _LOGGER.info("Pstryk prices for tomorrow confirmed")
            self.hass.bus.async_fire(EVENT_PRICES_CONFIRMED, {"entry_id": self.config_entry.entry_id, "at": iso(now)})
            self._prices_just_confirmed = True

    async def async_refresh_pstryk_daily(self) -> None:
        """Daily frames for the current month (and the previous one for spending history)."""
        now = self._now()
        local = dt_util.as_local(now)
        month_start_local = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        window_local = month_start_local
        if self.settings.ext.spends:
            window_local = (month_start_local - timedelta(days=1)).replace(day=1)
        start = dt_util.as_utc(window_local)
        try:
            raw = await self.pstryk.fetch_daily(start, now)
        except ProviderError as err:
            if isinstance(err, ProviderAuthError):
                self.status["pstryk"].fail(now, err)
            _LOGGER.debug("Pstryk daily refresh skipped: %s", err)
            return
        finally:
            self.cache.put_budget_state(self.pstryk.fingerprint, self.pstryk.budget.export())
        frames, self.monthly_summary = parse_daily(raw)
        self._apply_daily_frames(frames)
        self.cache.put("pstryk_daily", raw, now)
        if self.settings.ext.spends:
            self.history.add_spend_days(daily_totals(frames))
            self.history.schedule_save("state")
            if self.settings.ext.statistics_import:
                await async_import_statistics(self.hass, self.history.spend_days)
        self.async_update_listeners()

    def _apply_daily_frames(self, frames: list[MeterFrame]) -> None:
        """Keep only the current local month for the *_month sensors."""
        month = local_date(self._now()).strftime("%Y-%m")
        self.daily = [f for f in frames if local_date(f.start + (f.end - f.start) / 2).strftime("%Y-%m") == month]

    async def async_refresh_pstryk_monthly(self) -> None:
        """Monthly totals for the last 12 months (one small request per day)."""
        if not (self.settings.ext.spends and self.settings.ext.spends_history):
            return
        now = self._now()
        local = dt_util.as_local(now)
        first = local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        year, month = first.year, first.month - 12
        while month <= 0:
            month += 12
            year -= 1
        start = dt_util.as_utc(first.replace(year=year, month=month))
        try:
            raw = await self.pstryk.fetch_monthly(start, now)
        except ProviderError as err:
            _LOGGER.debug("Pstryk monthly refresh skipped: %s", err)
            return
        finally:
            self.cache.put_budget_state(self.pstryk.fingerprint, self.pstryk.budget.export())
        frames, _ = parse_daily(raw)
        self.history.add_spend_months(monthly_totals(frames))
        self.history.state["spends_monthly_at"] = iso(now)
        self.history.schedule_save("state")
        self.async_update_listeners()

    def _monthly_due(self) -> bool:
        if not (self.settings.ext.spends and self.settings.ext.spends_history):
            return False
        last = self.history.state.get("spends_monthly_at")
        if not last or not self.history.spend_months:
            return True
        return self._now() - datetime.fromisoformat(last.replace("Z", "+00:00")) > timedelta(hours=20)

    async def _on_spare_budget(self) -> None:
        """Use a spare request (never while waiting for tomorrow's prices) for monthly history."""
        local = dt_util.as_local(self._now())
        if 12 <= local.hour <= 17 and not self.snapshot.tomorrow_confirmed:
            return
        if self._monthly_due() and self.pstryk.budget.remaining() >= 1:
            await self.async_refresh_pstryk_monthly()

    @staticmethod
    def _same_day(a: datetime | None, b: datetime) -> bool:
        return a is not None and local_date(a) == local_date(b)

    @staticmethod
    def _has_complete_day(slots: list[PriceSlot], start: datetime, end: datetime) -> bool:
        hours = int((end - start).total_seconds() // 3600)
        return sum(1 for s in slots if start <= s.start < end and s.value is not None) >= hours

    @staticmethod
    def _merge_snapshot(old: PstrykSnapshot, new: PstrykSnapshot, now: datetime) -> PstrykSnapshot:
        """Keep confirmed prices from earlier responses (outage resilience)."""
        horizon_start = floor_hour(now) - timedelta(hours=48)

        def merge(a: list[PriceSlot], b: list[PriceSlot]) -> list[PriceSlot]:
            out = {s.start: s for s in a if s.start >= horizon_start}
            out.update({s.start: s for s in b})
            return [out[k] for k in sorted(out)]

        new.buy = merge(old.buy, new.buy)
        new.sell = merge(old.sell, new.sell)
        if not new.hourly:
            new.hourly = old.hourly
        tomorrow = local_date(now) + timedelta(days=1)
        t_start, t_end = local_day_bounds(datetime(tomorrow.year, tomorrow.month, tomorrow.day, 12, tzinfo=UTC))
        hours = int((t_end - t_start).total_seconds() // 3600)
        new.tomorrow_confirmed = sum(1 for s in new.buy if t_start <= s.start < t_end) >= hours
        return new

    # ===================================================== market refresh
    async def async_refresh_market(self) -> None:
        now = self._now()
        today = local_date(now)
        start = local_day_bounds(now - timedelta(days=3))[0]
        end = local_day_bounds(now + timedelta(days=1))[1]
        tasks = []
        if self.entsoe is not None:
            tasks.append(self._fetch_entsoe(start, end))
        if self.tge is not None:
            tasks.append(self._fetch_tge([today, today + timedelta(days=1)]))
        if self.settings.pse_enabled:
            tasks.append(self._fetch_rce(today - timedelta(days=3), today + timedelta(days=1)))
        if tasks:
            await asyncio.gather(*tasks)
        self.history.schedule_save("market")

    async def _fetch_entsoe(self, start: datetime, end: datetime) -> None:
        now = self._now()
        try:
            points = await self.entsoe.fetch_day_ahead(start, end)  # type: ignore[union-attr]
        except ProviderError as err:
            self.status["entsoe"].fail(now, err)
            if isinstance(err, ProviderAuthError):
                self._raise_issue("entsoe_auth", "entsoe_auth_failed")
            return
        self.history.add_market(points)
        self.status["entsoe"].ok(now)
        self._clear_issue("entsoe_auth")

    async def _fetch_tge(self, days: list[date]) -> None:
        now = self._now()
        got = 0
        for day in days:
            try:
                points = await self.tge.fetch_delivery_day(day)  # type: ignore[union-attr]
            except ProviderError as err:
                self.status["tge"].fail(now, err)
                return
            for p in points:
                p.provider = MARKET_PROVIDER_TGE
            got += self.history.add_market(points)
        self.status["tge"].ok(now)

    async def _fetch_rce(self, first: date, last: date) -> None:
        now = self._now()
        try:
            points = await self.pse.rce_prices(first, last)
        except ProviderError as err:
            self.status["pse"].fail(now, err)
            return
        self.history.add_market(points)
        self.status["pse"].ok(now)

    async def async_refresh_pse(self) -> None:
        if not self.settings.pse_enabled:
            return
        now = self._now()
        today = local_date(now)
        try:
            rows = await self.pse.system_forecast(today, today + timedelta(days=8))
        except ProviderError as err:
            self.status["pse"].fail(now, err)
            return
        self.history.add_system(rows)
        self.status["pse"].ok(now)
        self.history.schedule_save("system")

    async def async_refresh_weather(self) -> None:
        now = self._now()
        s = self.settings
        try:
            local, national = await asyncio.gather(
                self.weather.local_forecast(s.latitude, s.longitude), self.weather.national_forecast()
            )
        except ProviderError as err:
            self.status["weather"].fail(now, err)
            return
        self.local_weather = local
        self.national_weather = national
        # archive national features: only overwrite hours not yet in the past
        self.history.add_weather(w for w in national if w.start >= floor_hour(now) - timedelta(hours=1))
        self.cache.put("weather_local", [w.to_dict() for w in local], now)
        self.cache.put("weather_national", [w.to_dict() for w in national], now)
        self.status["weather"].ok(now)
        self.history.schedule_save("weather")

    # ========================================================== compute
    def market_reference(self) -> tuple[str, dict[datetime, float]]:
        """Return (provider, hourly series) used for training and published prices."""
        provider = self.settings.effective_market_provider
        series = self.history.market_series(provider)
        if provider != MARKET_PROVIDER_PSE_RCE and len(series) >= 24 * 30:
            return provider, series
        for alt in (MARKET_PROVIDER_ENTSOE, MARKET_PROVIDER_TGE):
            alt_series = self.history.market_series(alt)
            if len(alt_series) >= 24 * 30:
                return alt, alt_series
        rce = self.history.market_series(MARKET_PROVIDER_PSE_RCE)
        if len(rce) >= len(series):
            return f"{MARKET_PROVIDER_PSE_RCE}_proxy", rce
        return provider, series

    def published_market(self) -> dict[datetime, float]:
        """Day-ahead market prices that may be shown as PUBLISHED (never RCE)."""
        out: dict[datetime, float] = {}
        for provider in (MARKET_PROVIDER_TGE, MARKET_PROVIDER_ENTSOE):
            if provider == MARKET_PROVIDER_TGE and self.tge is None:
                continue
            out.update(self.history.market_series(provider))
        return out

    def feature_context(self) -> tuple[str, FeatureContext]:
        ref, series = self.market_reference()
        return ref, FeatureContext(prices=series, system=self.history.system, weather=self.history.weather)

    async def async_recalculate(self, *, reason: str, forecast: bool, snapshot: bool = False) -> None:
        data = await self._compute(reason=reason, forecast=forecast, snapshot=snapshot)
        self.async_set_updated_data(data)

    async def _compute(self, *, reason: str, forecast: bool, snapshot: bool = False) -> PstrykAIData:
        async with self._lock:
            now = self._now()
            s = self.settings
            ref, ctx = self.feature_context()
            confirmed_now = self._prices_just_confirmed
            if forecast or self.forecast_run is None or confirmed_now:
                sources = [ref]
                if self.history.system:
                    sources.append("pse_pk5l")
                if self.history.weather:
                    sources.append(f"open-meteo:{s.weather_model}")
                self.forecaster.mode = self.controls["forecast_model"]
                self.forecast_run = await self.hass.async_add_executor_job(
                    lambda: self.forecaster.forecast(ctx, now, horizon_hours=s.horizon_h, sources=sources)
                )
            if snapshot or confirmed_now:
                if self.forecast_run is not None:
                    self.history.add_snapshot(self.forecast_run)
                self.history.evaluate_snapshots(dict(ctx.prices), local_date)
                self.history.schedule_save("forecasts")
            self._prices_just_confirmed = False

            tariff = s.tariff
            if s.auto_calibrate:
                tariff.calibrate(
                    calibration_pairs(self.history.pstryk_buy, self.published_market() or dict(ctx.prices))
                )
            timeline = build_timeline(
                now,
                pstryk_buy=self.snapshot.buy,
                pstryk_sell=self.snapshot.sell,
                market_hourly=self.published_market(),
                forecast=self.forecast_run,
                tariff=tariff,
                horizon_hours=s.horizon_h,
                history_hours=max(0, int((now - local_day_bounds(now)[0]).total_seconds() // 3600)),
            )
            opt_timeline = timeline
            if self.controls.get("optimize_all_in"):
                opt_timeline = Timeline(
                    buy=s.tariff.all_in_slots(list(timeline.buy)), sell=timeline.sell, generated_at=now
                )
            self._last_timeline = timeline
            _, pv_sur, pv_sell = self.pv_maps()
            windows = (
                compute_windows(
                    opt_timeline,
                    now,
                    cheap_hours=int(self.controls["cheap_hours"]),
                    risk=s.risk_aversion,
                    speculative_h=s.max_speculative_h,
                )
                if self.controls["optimization_enabled"]
                else {}
            )
            schedules = (
                [
                    schedule_device(
                        p,
                        self.device_slots(list(opt_timeline.buy), p.power_kw, pv_sur, pv_sell),
                        now,
                        risk_aversion=s.risk_aversion,
                        max_speculative_hours=s.max_speculative_h,
                        current_value=self.inputs.value(f"device:{p.name}") if p.temperature_topic else None,
                    )
                    for p in sorted(s.profiles, key=lambda p: p.priority)
                ]
                if self.controls["optimization_enabled"]
                else []
            )
            self._last_timeline = timeline
            heat = await self.async_plan_heat(timeline, now, schedules)
            self.heat_plan = heat
            buffer = heat.plans.get("buffer") if heat else None
            dhw = heat.plans.get("dhw") if heat else None
            for p in (buffer, dhw):
                if p is not None:
                    self.history.add_decision(
                        {
                            "at": iso(now),
                            "storage": p.name,
                            "should_heat": p.should_heat,
                            "heater": p.heater_should_run,
                            "target": p.target_temperature,
                            "mode": p.mode,
                            "reason": reason,
                        }
                    )
                    self.history.schedule_save("state")
            prod, sur, _ = self.pv_maps()
            spends = (
                summarize(self.history.spend_days, self.history.spend_months, now) if self.settings.ext.spends else None
            )

            data = PstrykAIData(
                now=now,
                timeline=timeline,
                forecast=self.forecast_run,
                pstryk=self.snapshot,
                daily=self.daily,
                local_weather=self.local_weather,
                national_weather=self.national_weather,
                windows=windows,
                schedules=schedules,
                buffer=buffer,
                dhw=dhw,
                heat=heat,
                spends=spends,
                pv={"production": prod, "surplus": sur},
                providers={k: v.as_dict() for k, v in self.status.items()},
                model_info=self.model_info(),
                flags={
                    "reason": reason,
                    "advisory_mode": self.controls["advisory_mode"],
                    "optimization_enabled": self.controls["optimization_enabled"],
                    "tomorrow_confirmed": self.snapshot.tomorrow_confirmed,
                    "market_reference": ref,
                    "pstryk_budget_remaining": self.pstryk.budget.remaining(),
                },
            )
            self.last_recalc = now
        await self._publish(data)
        await self.async_notifications(data, data.heat, data.now)
        self.hass.bus.async_fire(EVENT_PLAN_UPDATED, {"entry_id": self.config_entry.entry_id, "reason": reason})
        return data

    def buffer_temperature(self) -> tuple[float | None, str]:
        """Current buffer temperature and its source: MQTT topic first, then HA entity."""
        return self._reading("buffer", self.settings.buffer_temp_topic, self.settings.buffer_temp_entity)

    def outdoor_temperature(self) -> tuple[float | None, str]:
        return self._reading("outdoor", self.settings.outdoor_temp_topic, self.settings.outdoor_temp_entity)

    def _reading(self, name: str, topic: str | None, entity_id: str | None) -> tuple[float | None, str]:
        if topic and (value := self.inputs.value(name)) is not None:
            return value, "mqtt"
        if (value := self._entity_float(entity_id)) is not None:
            return value, "entity"
        return None, ("mqtt_stale" if topic else "none")

    async def async_start_inputs(self) -> None:
        s = self.settings
        specs = [
            InputSpec("buffer", s.buffer_temp_topic or "", s.buffer_temp_key),
            InputSpec("outdoor", s.outdoor_temp_topic or "", s.outdoor_temp_key, min_value=-60, max_value=60),
        ]
        specs += [
            InputSpec(f"device:{p.name}", p.temperature_topic or "", p.temperature_key)
            for p in s.profiles
            if p.temperature_topic
        ]
        specs += self.heat_input_specs()
        self.inputs = MqttInputs(
            self.hass, specs, max_age=timedelta(minutes=s.input_max_age_min), on_update=self._on_input
        )
        if not await self.inputs.async_start():
            self._raise_issue("mqtt_inputs", "mqtt_inputs_unavailable")

    @callback
    def _on_input(self, name: str, value: float, previous: float | None) -> None:
        """Replan (MPC) when a measurement deviates from what the plan expected.

        Recalculations are limited to one per 5 minutes; a trigger inside that
        window is deferred (never dropped).
        """
        now = self._now()
        if name == "hp_power" or name.startswith("heater:"):
            self.integrate_power(now)
            self.async_update_listeners()
            return
        if not self._input_triggers(name, value, previous, now):
            self.async_update_listeners()
            return
        wait = timedelta(0)
        if self._last_input_recalc is not None:
            wait = self._last_input_recalc + timedelta(minutes=5) - now
        if wait <= timedelta(0):
            self._run_input_recalc(name)
            return
        if self._pending_input_recalc is None:

            @callback
            def _deferred(_now: datetime) -> None:
                self._pending_input_recalc = None
                self._run_input_recalc(name)

            self._pending_input_recalc = async_call_later(self.hass, wait.total_seconds(), _deferred)
        self.async_update_listeners()

    def _input_triggers(self, name: str, value: float, previous: float | None, now: datetime) -> bool:
        if previous is None:
            return True
        data = self.data
        if name in ("buffer", "buffer_bottom", "dhw_top", "dhw_bottom"):
            storage = "dhw" if name.startswith("dhw") else "buffer"
            plan = None if data is None else (data.dhw if storage == "dhw" else data.buffer)
            mean = self.storage_layers(storage)["mean"]
            if plan is not None and plan.steps and mean is not None:
                step = next((st for st in plan.steps if st.start <= now < st.start + timedelta(hours=1)), None)
                if step is not None:
                    frac = (now - step.start).total_seconds() / 3600
                    expected = step.temperature_start + (step.temperature_end - step.temperature_start) * frac
                    return abs(mean - expected) > 1.0
            return abs(value - previous) > 1.0
        if name.startswith("device:"):
            profile = next((p for p in self.settings.profiles if f"device:{p.name}" == name), None)
            if profile is not None and profile.target is not None:
                return (previous >= profile.target) != (value >= profile.target)
            return False
        return abs(value - previous) > 3.0

    @callback
    def _run_input_recalc(self, name: str) -> None:
        self._last_input_recalc = self._now()
        self.config_entry.async_create_background_task(
            self.hass, self.async_recalculate(reason=f"mqtt_input_{name}", forecast=False), f"{DOMAIN}_input_recalc"
        )

    def _entity_float(self, entity_id: str | None) -> float | None:
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        try:
            return float(state.state)
        except (TypeError, ValueError):
            return None

    async def _publish(self, data: PstrykAIData) -> None:
        if not self.controls["mqtt_enabled"]:
            return
        now = data.now
        msgs = build_messages(
            data,
            price_threshold=float(self.controls["price_threshold"]),
            evcc=self.settings.mqtt_evcc,
            include_sell=self.settings.prosumer or bool(self.snapshot.sell),
        )
        msgs += self.heat_messages(data.heat, now)
        if data.spends is not None:
            msgs += spend_messages(data.spends, now)
        sent = await self.publisher.async_publish(msgs, now)
        for topic, payload in self.command_messages(data.heat):
            await self.publisher.async_raw(topic, payload, retain=False)
        st = self.status["mqtt"]
        if sent:
            st.ok(now)
            if self.settings.mqtt_discovery and not self._discovery_sent:
                for topic, payload in discovery_messages(
                    self.publisher.prefix, self.config_entry.entry_id, self.publisher.topics
                ):
                    await self.publisher.async_raw(topic, payload)
                self._discovery_sent = True
            await self._clear_stale_topics()
        else:
            st.status = self.publisher.status
            st.last_attempt = now

    async def _clear_stale_topics(self) -> None:
        """Remove retained messages from topics that were renamed or disabled."""
        if self._stale_checked:
            return
        self._stale_checked = True
        current = {t for c in TOPICS if (t := self.publisher.topic(c))}
        previous = set(self.history.state.get("published_topics") or [])
        for topic in sorted(previous - current):
            await self.publisher.async_raw(topic, "", retain=True)
        if previous != current:
            self.history.state["published_topics"] = sorted(current)
            self.history.schedule_save("state")

    async def async_remove_discovery(self) -> None:
        for topic, payload in removal_messages(self.config_entry.entry_id):
            await self.publisher.async_raw(topic, payload)

    # ======================================================= training
    async def async_retrain(self) -> None:
        if self._training:
            return
        self._training = True
        try:
            ref, ctx = self.feature_context()
            now = self._now()
            state = await self.hass.async_add_executor_job(
                lambda: self.forecaster.train(ctx, market_reference=ref, now=now)
            )
            self.history.state["model"] = state.to_dict()
            self.history.schedule_save("state")
            _LOGGER.info("Model trained on %s (%s samples)", ref, state.training_samples)
        finally:
            self._training = False
        await self.async_recalculate(reason="retrained", forecast=True)

    def async_start_history_import(self, days: int | None = None) -> None:
        if self._import_task and not self._import_task.done():
            return
        self._import_task = self.config_entry.async_create_background_task(
            self.hass, self._import_history(days or self.settings.history_days), f"{DOMAIN}_history_import"
        )

    def history_is_short(self) -> bool:
        _, series = self.market_reference()
        return len(series) < 24 * 60

    async def _import_history(self, days: int) -> None:
        """Import public market/system/weather history (never Pstryk data)."""
        now = self._now()
        end_day = local_date(now)
        start_day = end_day - timedelta(days=days)
        self.import_status = {"state": "running", "started": iso(now), "days": days}
        done: dict[str, Any] = {}
        try:
            if self.entsoe is not None:
                try:
                    pts = await self.entsoe.fetch_day_ahead(
                        local_day_bounds(datetime(start_day.year, start_day.month, start_day.day, 12, tzinfo=UTC))[0],
                        now,
                    )
                    done["entsoe"] = self.history.add_market(pts)
                except ProviderError as err:
                    done["entsoe"] = f"error: {err}"
            if self.settings.pse_enabled:
                rce = pk5l = 0
                cursor = start_day
                while cursor < end_day:
                    chunk_end = min(end_day, cursor + timedelta(days=30))
                    try:
                        rce += self.history.add_market(await self.pse.rce_prices(cursor, chunk_end))
                        rows = await self.pse.system_forecast(cursor, chunk_end)
                        self.history.add_system(rows)
                        pk5l += len(rows)
                    except ProviderError as err:
                        done["pse_error"] = str(err)[:80]
                    cursor = chunk_end + timedelta(days=1)
                    await asyncio.sleep(1.0)  # be polite to the public API
                done["pse_rce"], done["pse_pk5l"] = rce, pk5l
            cursor = start_day
            hist_weather = 0
            while cursor < end_day:
                chunk_end = min(end_day - timedelta(days=1), cursor + timedelta(days=90))
                try:
                    rows = await self.weather.national_historical(cursor, chunk_end)
                    for r in rows:
                        self.history.weather.setdefault(r.start, r)
                    hist_weather += len(rows)
                except ProviderError as err:
                    done["weather_error"] = str(err)[:80]
                cursor = chunk_end + timedelta(days=1)
                await asyncio.sleep(1.0)
            done["weather"] = hist_weather
            await self.history.async_save_now()
            self.import_status = {"state": "done", "finished": iso(self._now()), **done}
        except asyncio.CancelledError:
            self.import_status = {"state": "cancelled"}
            raise
        await self.async_retrain()

    # ======================================================= diagnostics
    def model_info(self) -> dict[str, Any]:
        st = self.forecaster.state
        metrics = st.backtest.get("metrics", {}) if st.backtest else {}
        return {
            "mode": self.forecaster.mode,
            "market_reference": st.market_reference,
            "trained_at": st.trained_at,
            "training_samples": st.training_samples,
            "training_range": st.training_range,
            "weights": {str(k): v for k, v in st.weights.items()},
            "backtest_mae": {name: {k: v.get("mae") for k, v in per.items()} for name, per in metrics.items()},
            "backtest_origins": st.backtest.get("origins") if st.backtest else 0,
            "live_mae": self.history.live_mae(),
            "forecast_created_at": iso(self.forecast_run.created_at) if self.forecast_run else None,
            "forecast_model": self.forecast_run.model_name if self.forecast_run else None,
            "inputs_missing": self.forecast_run.inputs_missing if self.forecast_run else [],
            "history_hours": len(self.market_reference()[1]),
            "import": self.import_status,
            "mqtt_inputs": self.inputs.status(),
        }

    def set_control(self, key: str, value: Any) -> None:
        self.controls[key] = value
        self.history.state["controls"] = dict(self.controls)
        self.history.schedule_save("state")

    def _raise_issue(self, issue_id: str, key: str) -> None:
        ir.async_create_issue(
            self.hass,
            DOMAIN,
            f"{issue_id}_{self.config_entry.entry_id}",
            is_fixable=False,
            severity=ir.IssueSeverity.ERROR,
            translation_key=key,
        )

    def _clear_issue(self, issue_id: str) -> None:
        ir.async_delete_issue(self.hass, DOMAIN, f"{issue_id}_{self.config_entry.entry_id}")
