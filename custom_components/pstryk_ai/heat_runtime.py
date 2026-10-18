"""Runtime glue for heat storages, heaters, CWU, PV, learning, consumption,
commands, notifications and heartbeat (mixed into the coordinator)."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any

from .const import BOOST_FORMAT_SETPOINT, COMMAND_POWER, DHW_HP_VALVE, HP_STRATEGY_BOOST
from .learning import HourSample, LearningStore, fit_cop_ratio, fit_draw_profile, fit_losses
from .models.optimizer import BufferPlan
from .models.price_slot import PriceSlot, PriceSource, floor_hour, iso
from .mqtt.inputs import InputSpec
from .mqtt.schemas import Message, scalar
from .notify import KIND_FALLBACK, KIND_NEGATIVE, KIND_STALE, KIND_TOMORROW
from .optimization.dhw import draw_series, legionella_due, ready_constraints
from .optimization.heat_system import VALVE_DHW, HeatSystemPlan, StorageInput, plan_heat_system
from .optimization.thermal_storage import BufferConfig, mean_from_layers
from .pv import device_price, pv_forecast, surplus

if TYPE_CHECKING:
    from .timeline import Timeline

_LOGGER = logging.getLogger(__name__)

MAX_INTEGRATION_GAP = timedelta(minutes=15)


class HeatRuntimeMixin:
    """Expects the coordinator attributes (settings, inputs, history, controls, …)."""

    # ------------------------------------------------------------- inputs
    def heat_input_specs(self) -> list[InputSpec]:
        x = self.settings.ext
        specs = [InputSpec("buffer_bottom", x.buffer_bottom.topic or "", x.buffer_bottom.key)]
        if x.dhw.enabled:
            specs += [
                InputSpec("dhw_top", x.dhw.top.topic or "", x.dhw.top.key),
                InputSpec("dhw_bottom", x.dhw.bottom.topic or "", x.dhw.bottom.key),
            ]
        specs.append(InputSpec("hp_power", x.hp_power.topic or "", x.hp_power.key, min_value=0, max_value=100000))
        for name, heater in (("buffer", x.buffer_heater), ("dhw", x.dhw_heater)):
            if heater.enabled and heater.state_topic:
                specs.append(InputSpec(f"heater:{name}", heater.state_topic, heater.state_key, 0, 100000))
        return specs

    def storage_layers(self, name: str) -> dict[str, Any]:
        """Top, bottom, mean and stratification of a storage plus the reading source."""
        s = self.settings
        if name == "buffer":
            top, top_src = self.buffer_temperature()
            bottom, bottom_src = self._reading("buffer_bottom", s.ext.buffer_bottom.topic, s.ext.buffer_bottom.entity)
        else:
            top, top_src = self._reading("dhw_top", s.ext.dhw.top.topic, s.ext.dhw.top.entity)
            bottom, bottom_src = self._reading("dhw_bottom", s.ext.dhw.bottom.topic, s.ext.dhw.bottom.entity)
        if top is None and bottom is not None:
            top_src = "none"
        mean, strat = mean_from_layers(top, bottom)
        return {
            "top": top,
            "bottom": bottom,
            "mean": mean,
            "stratification": strat,
            "top_source": top_src,
            "bottom_source": bottom_src,
        }

    def hp_power_kw(self) -> float | None:
        x = self.settings.ext
        value, _ = self._reading("hp_power", x.hp_power.topic, x.hp_power.entity)
        if value is None:
            return None
        return value / 1000.0 if x.power_unit == "W" else value

    def heater_power_kw(self, name: str) -> float | None:
        heater = self.settings.ext.buffer_heater if name == "buffer" else self.settings.ext.dhw_heater
        if not (heater.enabled and heater.state_topic):
            return None
        value = self.inputs.value(f"heater:{name}")
        if value is None:
            return None
        if heater.command_format == COMMAND_POWER:
            return value
        # binary state: on = largest stage (electric input)
        big = heater.config.stages[-1]
        return big / max(heater.config.efficiency, 0.05) if value > 0.5 else 0.0

    # --------------------------------------------------------------- PV
    def pv_maps(self) -> tuple[dict[datetime, float], dict[datetime, float], dict[datetime, float]]:
        """(production kWh, surplus kWh, sell price) per hour; empty when PV is off."""
        if not self.controls.get("pv_enabled"):
            return {}, {}, {}
        prod = pv_forecast(self.local_weather, self.settings.ext.pv)
        sur = surplus(prod, self.settings.ext.pv)
        sell: dict[datetime, float] = {}
        if self.data is not None or self._last_timeline is not None:
            tl = self._last_timeline
            if tl is not None:
                sell = {s.start: s.value for s in tl.sell if s.value is not None}
        return prod, sur, sell

    def device_slots(self, slots: list[PriceSlot], load_kw: float, sur: dict, sell: dict) -> list[PriceSlot]:
        if not sur:
            return slots
        out = []
        for s in slots:
            price = device_price(s, sell.get(s.start, 0.0), sur.get(s.start, 0.0), load_kw)
            out.append(s if price is None or price == s.value else replace(s, value=price))
        return out

    # ------------------------------------------------------- heat system
    def _storage_configs(self, now: datetime) -> tuple[dict[str, StorageInput], dict[str, str]]:
        s = self.settings
        x = s.ext
        storages: dict[str, StorageInput] = {}
        reasons: dict[str, str] = {}
        learned = self.learning.results if x.learn_apply else {}
        if self.controls["buffer_enabled"]:
            cfg = replace(
                s.buffer,
                min_t=float(self.controls["buffer_min_t"]),
                max_t=max(float(self.controls["buffer_max_t"]), float(self.controls["buffer_min_t"]) + 1),
                comfort_penalty_pln_per_kh=100.0 if self.controls["buffer_strategy"] == "comfort" else 30.0,
                heater=x.buffer_heater.config
                if (x.buffer_heater.enabled and self.controls.get("buffer_heater_enabled"))
                else None,
                hp_max_t=x.hp_max_t,
            )
            if (fit := learned.get("buffer_losses")) is not None:
                cfg.building_kw_per_k = fit["building_kw_per_k"]
                cfg.loss_kw_per_k = fit["loss_kw_per_k"]
            layers = self.storage_layers("buffer")
            cfg.stratification_k = layers["stratification"]
            storages["buffer"] = StorageInput(cfg, layers["mean"], **self._strategy_args(x.boost_t))
            if layers["mean"] is None:
                reasons["buffer"] = (
                    f"Brak świeżego odczytu MQTT temperatury bufora (>{s.input_max_age_min} min) – sterowanie lokalne"
                    if layers["top_source"] == "mqtt_stale"
                    else "Brak odczytu temperatury bufora – sterowanie lokalne"
                )
        if x.dhw.enabled and self.controls.get("dhw_enabled"):
            d = x.dhw
            hour = floor_hour(now)
            hours = [hour + timedelta(hours=i) for i in range(72)]
            profile = learned.get("dhw_profile") if x.learn_apply else None
            if profile:
                demand = [profile[h.astimezone(self._tz).hour] for h in hours]
            else:
                demand = draw_series(hours, d.liters_per_day)
            legionella_t = None
            deadline = 24
            if d.legionella_enabled:
                last = self.history.state.get("legionella_done_at")
                due, deadline = legionella_due(datetime.fromisoformat(last) if last else None, now, d.legionella_days)
                legionella_t = d.legionella_t if due else None
            cfg = BufferConfig(
                name="dhw",
                volume_l=d.volume_l,
                min_t=d.min_t,
                max_t=d.max_t,
                target_t=d.target_t,
                hp_thermal_kw=s.buffer.hp_thermal_kw,
                hp_electric_kw=s.buffer.hp_electric_kw,
                loss_kw_per_k=d.loss_kw_per_k,
                building_kw_per_k=0.0,
                min_runtime_h=s.buffer.min_runtime_h,
                min_offtime_h=s.buffer.min_offtime_h,
                comfort_penalty_pln_per_kh=30.0,
                hp_levels=x.hp_levels,
                hp_kw_at_minus15=x.hp_kw_minus15,
                risk_aversion=s.risk_aversion,
                hp_enabled=d.hp_mode == DHW_HP_VALVE,
                hp_max_t=x.hp_max_t,
                heater=x.dhw_heater.config
                if (x.dhw_heater.enabled and self.controls.get("dhw_heater_enabled"))
                else None,
                demand_kw=demand,
                ready=ready_constraints(now, d.ready_times, d.ready_t),
                legionella_t=legionella_t,
                legionella_deadline_h=deadline,
            )
            layers = self.storage_layers("dhw")
            cfg.stratification_k = layers["stratification"]
            storages["dhw"] = StorageInput(cfg, layers["mean"], **self._strategy_args(x.dhw_boost_t))
            if layers["mean"] is None:
                reasons["dhw"] = "Brak odczytu temperatury CWU – sterowanie lokalne"
        return storages, reasons

    def _strategy_args(self, boost_t: float) -> dict[str, Any]:
        x = self.settings.ext
        strategy = "boost" if self.controls.get("heat_pump_strategy", x.hp_strategy) == HP_STRATEGY_BOOST else "full"
        return {"strategy": strategy, "boost_t": boost_t, "boost_percentile": x.boost_share}

    async def async_plan_heat(self, timeline: Timeline, now: datetime, schedules: list) -> HeatSystemPlan | None:
        storages, reasons = self._storage_configs(now)
        if not storages:
            return None
        s = self.settings
        x = s.ext
        slots = timeline.buy
        if self.controls.get("optimize_all_in"):
            slots = s.tariff.all_in_slots(list(slots))
        cur = timeline.at(now)
        stale_prices = (
            cur is None
            or cur.source is PriceSource.UNAVAILABLE
            or (
                self.snapshot.fetched_at is not None
                and now - self.snapshot.fetched_at > timedelta(hours=26)
                and cur.source is not PriceSource.ACTUAL_PSTRYK
            )
        )
        for item in storages.values():
            item.stale = stale_prices
        outdoor = {w.start: w.get("temperature_2m") for w in self.local_weather if w.get("temperature_2m") is not None}
        if (t_out := self.outdoor_temperature()[0]) is not None:
            outdoor[floor_hour(now)] = t_out
        other: dict[datetime, float] = {}
        if self.controls.get("power_limit_enabled"):
            for sl in slots:
                other[sl.start] = x.base_load_kw
            profiles = {p.name: p for p in s.profiles}
            for sch in schedules:
                kw = profiles[sch.profile].power_kw if sch.profile in profiles else 0.0
                for h in sch.slots:
                    other[h] = other.get(h, 0.0) + kw
        _, sur, sell = self.pv_maps()
        cop = s.cop
        if x.learn_apply and (ratio := self.learning.results.get("cop_ratio")):
            cop = replace(cop, calibration=ratio)
        valve_shared = x.dhw.hp_mode == DHW_HP_VALVE
        plan = await self.hass.async_add_executor_job(
            lambda: plan_heat_system(
                storages,
                cop,
                now=now,
                slots=slots,
                outdoor_forecast=outdoor,
                shared_hp=valve_shared,
                priority="dhw" if x.dhw.priority else "buffer",
                power_limit_kw=x.power_limit_kw if self.controls.get("power_limit_enabled") else None,
                other_load_kw=other,
                sell_prices=sell if sur else None,
                surplus_kwh=sur or None,
                advisory=bool(self.controls["advisory_mode"]),
                fallback_reason=reasons,
            )
        )
        self._track_legionella(now)
        return plan

    def _track_legionella(self, now: datetime) -> None:
        d = self.settings.ext.dhw
        if not (d.enabled and d.legionella_enabled):
            return
        top = self.storage_layers("dhw")["top"]
        if top is not None and top >= d.legionella_t - 0.2:
            self.history.state["legionella_done_at"] = iso(now)
            self.history.schedule_save("state")

    # -------------------------------------------------------- consumption
    def integrate_power(self, now: datetime) -> None:
        """Accumulate measured heat-pump / heater energy and cost per local day."""
        last = self._power_last
        current = {
            "hp": self.hp_power_kw(),
            "heater_buffer": self.heater_power_kw("buffer"),
            "heater_dhw": self.heater_power_kw("dhw"),
        }
        if last is not None:
            t_prev, values = last
            gap = now - t_prev
            if timedelta(0) < gap <= MAX_INTEGRATION_GAP:
                price = None
                tl = self._last_timeline
                if tl is not None and (slot := tl.at(t_prev)) is not None:
                    price = slot.value
                day = now.astimezone(self._tz).date().isoformat()
                store = self.history.state.setdefault("consumption", {}).setdefault(day, {})
                for key, kw in values.items():
                    if kw is None:
                        continue
                    kwh = kw * gap.total_seconds() / 3600
                    item = store.setdefault(key, {"kwh": 0.0, "cost": 0.0})
                    item["kwh"] = round(item["kwh"] + kwh, 5)
                    if price is not None:
                        item["cost"] = round(item["cost"] + kwh * price, 5)
                cons = self.history.state["consumption"]
                for old in sorted(cons)[:-62]:
                    del cons[old]
                self.history.schedule_save("state")
        self._power_last = (now, current)

    def consumption(self, day: str | None = None) -> dict[str, dict[str, float]]:
        cons = self.history.state.get("consumption") or {}
        if day is None:
            day = self._now().astimezone(self._tz).date().isoformat()
        return cons.get(day, {})

    def consumption_month(self) -> dict[str, dict[str, float]]:
        month = self._now().astimezone(self._tz).strftime("%Y-%m")
        out: dict[str, dict[str, float]] = {}
        for day, items in (self.history.state.get("consumption") or {}).items():
            if not day.startswith(month):
                continue
            for key, v in items.items():
                acc = out.setdefault(key, {"kwh": 0.0, "cost": 0.0})
                acc["kwh"] = round(acc["kwh"] + v.get("kwh", 0.0), 4)
                acc["cost"] = round(acc["cost"] + v.get("cost", 0.0), 4)
        return out

    # ----------------------------------------------------------- learning
    def learning_tick(self, now: datetime, plan: HeatSystemPlan | None) -> None:
        x = self.settings.ext
        if not (x.learn_losses or x.learn_dhw_profile or x.learn_cop):
            return
        hour = floor_hour(now)
        prev = self._learn_prev
        t_out = self.outdoor_temperature()[0]
        if t_out is None:
            t_out = next((w.get("temperature_2m") for w in self.local_weather if w.start == hour), None)
        means = {n: self.storage_layers(n)["mean"] for n in ("buffer", "dhw")}
        cons = self.consumption()
        if prev is not None and prev["hour"] == hour - timedelta(hours=1) and t_out is not None:
            for name, mean in means.items():
                start_t = prev["means"].get(name)
                if mean is None or start_t is None:
                    continue
                hp_kwh = None
                heater_kwh = None
                if self.hp_power_kw() is not None:
                    hp_total = cons.get("hp", {}).get("kwh", 0.0) - prev["cons"].get("hp", 0.0)
                    served = prev["valve"] == (VALVE_DHW if name == "dhw" else "buffer") or prev["valve"] is None
                    hp_kwh = max(0.0, hp_total) if served else 0.0
                hk = f"heater_{name}"
                if hk in cons:
                    heater_kwh = max(0.0, cons[hk]["kwh"] - prev["cons"].get(hk, 0.0))
                self.learning.add(
                    name,
                    HourSample(
                        prev["hour"], start_t, mean, float(t_out), hp_kwh, heater_kwh, prev["heating"].get(name, False)
                    ),
                )
            self._refit_learning()
        heating = {}
        valve = None
        if plan is not None:
            for name, p in plan.plans.items():
                heating[name] = bool(p.steps and p.steps[0].thermal_kwh > 0)
            valve = plan.valve_now
        self._learn_prev = {
            "hour": hour,
            "means": means,
            "cons": {k: v.get("kwh", 0.0) for k, v in cons.items()},
            "heating": heating,
            "valve": valve,
        }
        self.history.state["learning"] = self.learning.to_dict()
        self.history.schedule_save("state")

    def _refit_learning(self) -> None:
        x = self.settings.ext
        s = self.settings
        res = self.learning.results
        if x.learn_losses and (rows := self.learning.samples.get("buffer")):
            fit = fit_losses(rows, s.buffer.capacity, s.buffer.base_t)
            if fit:
                res["buffer_losses"] = fit
        if x.learn_dhw_profile and (rows := self.learning.samples.get("dhw")):
            cap = x.dhw.volume_l * 0.001163
            prof = fit_draw_profile(rows, cap, x.dhw.loss_kw_per_k)
            if prof:
                res["dhw_profile"] = prof
        if x.learn_cop and (rows := self.learning.samples.get("buffer")):
            loss = (res.get("buffer_losses") or {}).get("loss_kw_per_k", s.buffer.loss_kw_per_k)
            ratio = fit_cop_ratio(rows, s.buffer.capacity, loss, s.cop.cop)
            if ratio:
                res["cop_ratio"] = ratio

    # ------------------------------------------------------------ commands
    def command_messages(self, plan: HeatSystemPlan | None) -> list[tuple[str, str]]:
        """(absolute topic, payload) for the user's actuators – only in control mode."""
        if plan is None or self.controls["advisory_mode"]:
            return []
        x = self.settings.ext
        out: list[tuple[str, str]] = []
        for name, heater in (("buffer", x.buffer_heater), ("dhw", x.dhw_heater)):
            p = plan.plans.get(name)
            if p is None or not (heater.enabled and heater.command_topic):
                continue
            run = p.mode == "control" and p.heater_should_run
            if heater.command_format == COMMAND_POWER:
                payload = f"{p.heater_power_kw:.1f}" if run else "0"
            else:
                payload = "1" if run else "0"
            out.append((heater.command_topic, payload))
        for name, topic in (("buffer", x.boost_topic), ("dhw", x.dhw_boost_topic)):
            p = plan.plans.get(name)
            if p is None or not topic or p.strategy != "boost":
                continue
            run = p.mode == "control" and p.should_heat
            if x.boost_format == BOOST_FORMAT_SETPOINT:
                payload = f"{p.boost_target_t or 0:.1f}" if run else "0"
            else:
                payload = "1" if run else "0"
            out.append((topic, payload))
        full = any(p.strategy != "boost" for p in plan.plans.values())
        # in boost mode the valve stays with the heat pump's own controller
        if full and x.dhw.enabled and x.dhw.valve_topic and x.dhw.hp_mode == DHW_HP_VALVE:
            fallback = any(p.mode == "fallback" for p in plan.plans.values())
            out.append((x.dhw.valve_topic, "idle" if fallback else plan.valve_now))
        return out

    def heat_messages(self, plan: HeatSystemPlan | None, now: datetime) -> list[Message]:
        msgs: list[Message] = []
        if plan is None:
            return msgs
        for name, p in plan.plans.items():
            base = "optimizer/buffer" if name == "buffer" else "optimizer/dhw"
            expiry = max(60, int((p.valid_until - now).total_seconds()))
            if name == "dhw":
                msgs += [
                    Message(f"{base}/should_heat", scalar(p.should_heat), retain=False, expiry_s=expiry),
                    Message(f"{base}/mode", p.mode),
                    Message(f"{base}/target_temperature", scalar(p.target_temperature)),
                    Message(f"{base}/next_start", scalar(p.recommended_start)),
                    Message(f"{base}/schedule", _plan_json(p, now)),
                ]
            boost_now = p.strategy == "boost" and p.mode != "fallback" and p.should_heat
            msgs += [
                Message(f"{base}/boost", scalar(boost_now), retain=False, expiry_s=expiry),
                Message(f"{base}/boost_target", scalar(p.boost_target_t if boost_now else None)),
                Message(f"{base}/strategy", p.strategy),
                Message(f"{base}/hp_modulation", scalar(p.hp_modulation_pct), retain=False, expiry_s=expiry),
                Message(f"{base}/heater/should_run", scalar(p.heater_should_run), retain=False, expiry_s=expiry),
                Message(f"{base}/heater/power", scalar(round(p.heater_power_kw, 2))),
                Message(f"{base}/soc", scalar(None if p.soc_pct is None else round(p.soc_pct, 1))),
            ]
        msgs.append(Message("optimizer/valve", plan.valve_now, retain=False, expiry_s=4500))
        return msgs

    # ------------------------------------------------------- notifications
    async def async_notifications(self, data: Any, plan: HeatSystemPlan | None, now: datetime) -> None:
        n = self.notifier
        if not any(n.enabled.values()):
            return
        tomorrow = data.day(1)
        if data.day_confirmed(1) and tomorrow:
            vals = [s for s in tomorrow if s.value is not None]
            if vals:
                cheapest = min(vals, key=lambda s: s.value)
                dearest = max(vals, key=lambda s: s.value)
                avg = sum(s.value for s in vals) / len(vals)
                day_key = tomorrow[0].start.astimezone(self._tz).date().isoformat()
                await n.async_send(
                    KIND_TOMORROW,
                    "Pstryk AI – ceny na jutro",
                    f"Średnia {avg:.3f} zł/kWh. Najtaniej {self._hhmm(cheapest.start)} ({cheapest.value:.3f}), "
                    f"najdrożej {self._hhmm(dearest.start)} ({dearest.value:.3f}).",
                    dedup=day_key,
                )
                negative = [s for s in vals if s.value < 0]
                if negative:
                    hours = ", ".join(self._hhmm(s.start) for s in negative)
                    await n.async_send(
                        KIND_NEGATIVE,
                        "Pstryk AI – ujemne ceny jutro",
                        f"Ujemna cena energii jutro o: {hours}. Dobry moment na grzanie i ładowanie.",
                        dedup=day_key,
                    )
        if plan is not None:
            fallback = [name for name, p in plan.plans.items() if p.mode == "fallback"]
            if fallback:
                names = ", ".join("bufor" if f == "buffer" else "CWU" for f in fallback)
                await n.async_send(
                    KIND_FALLBACK,
                    "Pstryk AI – sterowanie lokalne",
                    f"Brak aktualnych danych dla: {names}. Pstryk AI nie wydaje zaleceń – działa sterowanie lokalne.",
                    dedup="active",
                )
            else:
                n.reset(KIND_FALLBACK)
        fetched = self.snapshot.fetched_at
        if fetched is not None and now - fetched > timedelta(hours=3) and self.status["pstryk"].status != "ok":
            await n.async_send(
                KIND_STALE,
                "Pstryk AI – brak aktualnych danych",
                f"Ostatnie dane z Pstryk: {self._hhmm(fetched)} (status: {self.status['pstryk'].status}).",
                dedup="active",
            )
        elif self.status["pstryk"].status == "ok":
            n.reset(KIND_STALE)

    def _hhmm(self, moment: datetime) -> str:
        return moment.astimezone(self._tz).strftime("%H:%M")


def _plan_json(plan: BufferPlan, now: datetime) -> str:
    from .mqtt.schemas import envelope

    return envelope(f"{plan.name}_plan", plan.to_dict(), now, plan.valid_until)


def new_learning_store(data: dict[str, Any] | None) -> LearningStore:
    return LearningStore.from_dict(data)
