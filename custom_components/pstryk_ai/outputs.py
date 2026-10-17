"""Computed result container and MQTT message assembly (pure Python)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import json
from statistics import fmean
from typing import Any

from .api.weather import WeatherHour
from .models.energy_data import MeterFrame, PstrykSnapshot
from .models.forecasts import ForecastRun
from .models.optimizer import BufferPlan, DeviceSchedule, Window
from .models.price_slot import PriceSlot, PriceSource, iso
from .mqtt.schemas import Message, compact_series, envelope, evcc_payload, local_day_slots, records, scalar
from .optimization.cheapest_hours import best_window, cheapest_n, classify
from .timeline import Timeline

WINDOW_SIZES = (1, 2, 3, 4, 6, 8)


@dataclass
class PstrykAIData:
    now: datetime
    timeline: Timeline
    forecast: ForecastRun | None
    pstryk: PstrykSnapshot | None
    daily: list[MeterFrame] = field(default_factory=list)
    local_weather: list[WeatherHour] = field(default_factory=list)
    national_weather: list[WeatherHour] = field(default_factory=list)
    windows: dict[str, Window | None] = field(default_factory=dict)
    schedules: list[DeviceSchedule] = field(default_factory=list)
    buffer: BufferPlan | None = None
    dhw: BufferPlan | None = None
    heat: Any = None  # HeatSystemPlan
    spends: Any = None  # SpendsSummary
    pv: dict[str, Any] = field(default_factory=dict)
    providers: dict[str, dict[str, Any]] = field(default_factory=dict)
    model_info: dict[str, Any] = field(default_factory=dict)
    flags: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------ helpers
    @property
    def current(self) -> PriceSlot | None:
        return self.timeline.at(self.now)

    @property
    def next(self) -> PriceSlot | None:
        return self.timeline.at(self.now + timedelta(hours=1))

    def current_sell(self) -> PriceSlot | None:
        return self.timeline.at(self.now, "sell")

    def day(self, offset: int, kind: str = "buy") -> list[PriceSlot]:
        slots = self.timeline.buy if kind == "buy" else self.timeline.sell
        return local_day_slots(slots, offset, self.now)

    def future(self, hours: int, kind: str = "buy") -> list[PriceSlot]:
        start = self.now.replace(minute=0, second=0, microsecond=0)
        return self.timeline.between(start, start + timedelta(hours=hours), kind)

    def average(self, slots: list[PriceSlot]) -> float | None:
        values = [s.value for s in slots if s.value is not None]
        return fmean(values) if values else None

    def day_confirmed(self, offset: int) -> bool:
        slots = self.day(offset)
        return bool(slots) and all(s.source is PriceSource.ACTUAL_PSTRYK for s in slots)

    def forecast_confidence(self) -> float | None:
        values = [s.confidence for s in self.future(168) if s.source.is_forecast and s.confidence is not None]
        return fmean(values) if values else None

    def cheap_probability(self, threshold: float, hours: int = 24) -> float | None:
        """Share of upcoming hours expected below ``threshold`` (interval-aware)."""
        slots = [s for s in self.future(hours) if s.value is not None]
        if not slots:
            return None
        acc = 0.0
        for s in slots:
            if s.source.is_forecast and s.p10 is not None and s.p90 is not None and s.p90 > s.p10:
                # linear CDF between P10 and P90 (10% tails outside)
                if threshold <= s.p10:
                    acc += 0.1 * max(0.0, 1 - (s.p10 - threshold) / max(s.p90 - s.p10, 1e-6))
                elif threshold >= s.p90:
                    acc += 0.9 + 0.1 * min(1.0, (threshold - s.p90) / max(s.p90 - s.p10, 1e-6))
                else:
                    acc += 0.1 + 0.8 * (threshold - s.p10) / (s.p90 - s.p10)
            else:
                acc += 1.0 if (s.value or 0) <= threshold else 0.0
        return acc / len(slots)


def compute_windows(
    timeline: Timeline, now: datetime, *, cheap_hours: int, risk: float, speculative_h: int
) -> dict[str, Window | None]:
    out: dict[str, Window | None] = {}
    slots = timeline.buy
    for h in WINDOW_SIZES:
        out[f"best_{h}h"] = best_window(slots, h, now=now, risk_aversion=risk, max_speculative_hours=speculative_h)
        out[f"best_{h}h_24h"] = best_window(slots, h, now=now, deadline=now + timedelta(hours=24), risk_aversion=risk)
    out["cheapest_n_24h"] = cheapest_n(
        slots, cheap_hours, now=now, deadline=now + timedelta(hours=24), risk_aversion=risk
    )
    out["cheapest_n_168h"] = cheapest_n(slots, cheap_hours, now=now, risk_aversion=risk)
    out["most_expensive_1h_24h"] = best_window(
        slots, 1, now=now, deadline=now + timedelta(hours=24), most_expensive=True
    )
    out["most_expensive_3h_24h"] = best_window(
        slots, 3, now=now, deadline=now + timedelta(hours=24), most_expensive=True
    )
    return out


def _w(window: Window | None) -> dict[str, Any] | None:
    return window.to_dict() if window else None


def build_messages(
    data: PstrykAIData,
    *,
    price_threshold: float,
    evcc: bool,
    include_sell: bool,
) -> list[Message]:
    now = data.now
    valid = data.timeline.buy[0].valid_until if data.timeline.buy else None
    valid = valid or now + timedelta(hours=1)
    msgs: list[Message] = []
    cur, nxt = data.current, data.next

    msgs.append(Message("availability", "online"))
    msgs.append(Message("prices/current", scalar(cur.value if cur else None)))
    msgs.append(Message("prices/current/json", envelope("price", cur.as_record() if cur else None, now, valid)))
    msgs.append(Message("prices/next", scalar(nxt.value if nxt else None)))
    msgs.append(Message("prices/today", envelope("prices_today", records(data.day(0)), now, valid, "PLN/kWh")))
    msgs.append(Message("prices/tomorrow", envelope("prices_tomorrow", records(data.day(1)), now, valid, "PLN/kWh")))
    confirmed = [s for s in data.timeline.buy if s.source is PriceSource.ACTUAL_PSTRYK]
    msgs.append(Message("prices/pstryk/buy", envelope("pstryk_buy", records(confirmed), now, valid, "PLN/kWh")))
    if include_sell:
        sell_conf = [s for s in data.timeline.sell if s.source is PriceSource.ACTUAL_PSTRYK]
        msgs.append(Message("prices/pstryk/sell", envelope("pstryk_sell", records(sell_conf), now, valid, "PLN/kWh")))
    tge = [s for s in data.timeline.buy if s.source is PriceSource.PUBLISHED_TGE]
    msgs.append(
        Message(
            "prices/tge",
            envelope(
                "market_published",
                [{**s.as_record(), "market_pln_mwh": s.meta.get("market_pln_mwh")} for s in tge],
                now,
                valid,
                "PLN/kWh",
            ),
        )
    )
    horizon = data.future(168)
    msgs.append(Message("prices/forecast/7d", envelope("forecast_7d", compact_series(horizon), now, valid, "PLN/kWh")))
    for day in range(1, 8):
        msgs.append(
            Message(
                f"prices/forecast/day/{day}",
                envelope(f"forecast_day_{day}", records(data.day(day)), now, valid, "PLN/kWh"),
            )
        )

    flags = classify(cur, data.future(24)) if cur else {"cheap": None}
    cheap_now = bool(flags.get("cheap")) or (cur is not None and cur.value is not None and cur.value <= price_threshold)
    msgs.append(Message("cheap/now", scalar(cheap_now)))
    best3 = data.windows.get("best_3h_24h")
    msgs.append(Message("cheap/next_start", scalar(best3.start if best3 else None)))
    for key, topic in (
        ("best_2h_24h", "best_2h"),
        ("best_4h_24h", "best_4h"),
        ("best_6h_24h", "best_6h"),
        ("cheapest_n_24h", "best_24h"),
    ):
        msgs.append(Message(f"cheap/{topic}", envelope("window", _w(data.windows.get(key)), now, valid, "PLN/kWh")))
    msgs.append(
        Message(
            "cheap/schedule",
            envelope(
                "schedule",
                {
                    "windows": {k: _w(v) for k, v in data.windows.items()},
                    "devices": [s.to_dict() for s in data.schedules],
                },
                now,
                valid,
            ),
        )
    )

    # weather
    hour = now.replace(minute=0, second=0, microsecond=0)
    lw = {w.start: w for w in data.local_weather}
    current_w = lw.get(hour)
    msgs.append(
        Message("weather/current", envelope("weather_current", current_w.to_dict() if current_w else None, now, valid))
    )
    fut_w = [w for w in data.local_weather if w.start >= hour][:168]
    msgs.append(
        Message(
            "weather/forecast",
            envelope(
                "weather_forecast",
                {
                    "start": [iso(w.start) for w in fut_w],
                    "temperature_2m": [w.get("temperature_2m") for w in fut_w],
                    "wind_speed_120m": [w.get("wind_speed_120m") for w in fut_w],
                    "shortwave_radiation": [w.get("shortwave_radiation") for w in fut_w],
                    "cloud_cover": [w.get("cloud_cover") for w in fut_w],
                    "precipitation": [w.get("precipitation") for w in fut_w],
                },
                now,
                valid,
            ),
        )
    )
    msgs.append(Message("weather/temperature", scalar(current_w.get("temperature_2m") if current_w else None)))
    nat = [w for w in data.national_weather if w.start >= hour][:168]
    msgs.append(
        Message(
            "weather/wind",
            envelope(
                "national_wind_index",
                [{"start": iso(w.start), "value": _r(w.get("national_wind_index"))} for w in nat],
                now,
                valid,
            ),
        )
    )
    msgs.append(
        Message(
            "weather/solar",
            envelope(
                "national_solar_index",
                [{"start": iso(w.start), "value": _r(w.get("national_solar_index"))} for w in nat],
                now,
                valid,
                "W/m2",
            ),
        )
    )

    # buffer
    plan = data.buffer
    if plan is not None:
        expiry = max(60, int((plan.valid_until - now).total_seconds()))
        msgs.append(Message("optimizer/buffer/should_heat", scalar(plan.should_heat), retain=False, expiry_s=expiry))
        msgs.append(Message("optimizer/buffer/mode", plan.mode))
        msgs.append(Message("optimizer/buffer/target_temperature", scalar(plan.target_temperature)))
        msgs.append(Message("optimizer/buffer/next_start", scalar(plan.recommended_start)))
        msgs.append(Message("optimizer/buffer/next_stop", scalar(plan.recommended_stop)))
        msgs.append(Message("optimizer/buffer/expected_cost", scalar(round(plan.expected_cost_pln, 3))))
        msgs.append(
            Message("optimizer/buffer/schedule", envelope("buffer_plan", plan.to_dict(), now, plan.valid_until))
        )

    # system
    conf = data.forecast_confidence()
    msgs.append(
        Message(
            "status",
            json.dumps(
                {"schema": "pstryk_ai/v1", "generated_at": iso(now), **data.flags, "providers": data.providers},
                separators=(",", ":"),
            ),
        )
    )
    msgs.append(Message("forecast/status", json.dumps(data.model_info, separators=(",", ":"), default=str)))
    msgs.append(Message("forecast/confidence", scalar(None if conf is None else round(conf, 3))))
    msgs.append(Message("forecast/last_update", scalar(data.forecast.created_at if data.forecast else None)))
    for name in ("pstryk", "tge", "entsoe", "pse", "weather"):
        info = data.providers.get(name)
        if info is not None:
            msgs.append(Message(f"api/{name}/status", info.get("status", "unknown")))
    if evcc:
        msgs.append(Message("evcc/prices", evcc_payload([s for s in horizon if s.value is not None])))
    return msgs


def _r(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def spend_messages(spends: Any, now: datetime) -> list[Message]:
    """Pstryk spending summary topics (daily/monthly history)."""
    valid = now + timedelta(hours=6)
    return [
        Message("spends/summary", envelope("spends_summary", spends.to_dict(), now, valid, "PLN")),
        Message("spends/daily", envelope("spends_daily", spends.days, now, valid, "PLN")),
        Message("spends/monthly", envelope("spends_monthly", spends.months, now, valid, "PLN")),
    ]
