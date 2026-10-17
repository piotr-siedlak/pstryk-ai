"""Unified customer price timeline with strict source precedence.

ACTUAL_PSTRYK > PUBLISHED_TGE (market price published, tariff applied)
> MODEL_FORECAST > FALLBACK_FORECAST > UNAVAILABLE
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .forecasting.baseline import MODEL_NAME as BASELINE_NAME
from .models.forecasts import ForecastRun
from .models.price_slot import PriceSlot, PriceSource, floor_hour
from .tariff import Tariff


@dataclass(slots=True)
class Timeline:
    buy: list[PriceSlot] = field(default_factory=list)
    sell: list[PriceSlot] = field(default_factory=list)
    generated_at: datetime | None = None

    def at(self, moment: datetime, kind: str = "buy") -> PriceSlot | None:
        for slot in self.buy if kind == "buy" else self.sell:
            if slot.contains(moment):
                return slot
        return None

    def between(self, start: datetime, end: datetime, kind: str = "buy") -> list[PriceSlot]:
        slots = self.buy if kind == "buy" else self.sell
        return [s for s in slots if start <= s.start < end]


def build_timeline(
    now: datetime,
    *,
    pstryk_buy: list[PriceSlot],
    pstryk_sell: list[PriceSlot],
    market_hourly: Mapping[datetime, float],
    forecast: ForecastRun | None,
    tariff: Tariff,
    horizon_hours: int = 168,
    history_hours: int = 0,
    valid_hours: int = 6,
) -> Timeline:
    start = floor_hour(now) - timedelta(hours=history_hours)
    end = floor_hour(now) + timedelta(hours=horizon_hours)
    valid_until = now + timedelta(hours=valid_hours)
    buy_actual = {floor_hour(s.start): s for s in pstryk_buy}
    sell_actual = {floor_hour(s.start): s for s in pstryk_sell}
    fc = {p.forecast_for: p for p in (forecast.points if forecast else [])}

    buy: list[PriceSlot] = []
    sell: list[PriceSlot] = []
    t = start
    while t < end:
        t_end = t + timedelta(hours=1)
        # ---------------------------------------------------------- buy
        if t in buy_actual:
            buy.append(buy_actual[t])
        elif t in market_hourly:
            m = market_hourly[t]
            buy.append(
                PriceSlot(
                    t,
                    t_end,
                    tariff.energy_price(m),
                    PriceSource.PUBLISHED_TGE,
                    generated_at=now,
                    valid_until=valid_until,
                    meta={"market_pln_mwh": round(m, 2)},
                )
            )
        elif t in fc:
            p = fc[t]
            src = PriceSource.FALLBACK_FORECAST if p.model_name == BASELINE_NAME else PriceSource.MODEL_FORECAST
            buy.append(
                PriceSlot(
                    t,
                    t_end,
                    tariff.energy_price(p.prediction_p50),
                    src,
                    p10=tariff.energy_price(p.prediction_p10),
                    p50=tariff.energy_price(p.prediction_p50),
                    p90=tariff.energy_price(p.prediction_p90),
                    confidence=p.confidence,
                    model_name=p.model_name,
                    generated_at=p.forecast_created_at,
                    valid_until=valid_until,
                    meta={"market_pln_mwh": round(p.prediction_p50, 2), "horizon_h": p.forecast_horizon_hours},
                )
            )
        else:
            buy.append(PriceSlot(t, t_end, None, PriceSource.UNAVAILABLE, generated_at=now))
        # --------------------------------------------------------- sell
        if t in sell_actual:
            sell.append(sell_actual[t])
        elif t in market_hourly:
            sell.append(
                PriceSlot(
                    t,
                    t_end,
                    tariff.sell_price(market_hourly[t]),
                    PriceSource.PUBLISHED_TGE,
                    generated_at=now,
                    valid_until=valid_until,
                )
            )
        elif t in fc:
            p = fc[t]
            src = PriceSource.FALLBACK_FORECAST if p.model_name == BASELINE_NAME else PriceSource.MODEL_FORECAST
            sell.append(
                PriceSlot(
                    t,
                    t_end,
                    tariff.sell_price(p.prediction_p50),
                    src,
                    p10=tariff.sell_price(p.prediction_p10),
                    p50=tariff.sell_price(p.prediction_p50),
                    p90=tariff.sell_price(p.prediction_p90),
                    confidence=p.confidence,
                    model_name=p.model_name,
                    generated_at=p.forecast_created_at,
                    valid_until=valid_until,
                )
            )
        else:
            sell.append(PriceSlot(t, t_end, None, PriceSource.UNAVAILABLE, generated_at=now))
        t = t_end
    return Timeline(buy=buy, sell=sell, generated_at=now)
