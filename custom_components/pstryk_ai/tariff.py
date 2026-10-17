"""Tariff model: converts market prices (PLN/MWh) into customer prices (PLN/kWh).

Three distinct quantities are never mixed:

* **energy price** – what Pstryk reports as ``price_gross`` (energy component,
  gross). For non-confirmed slots it is *estimated* from the market price:
  ``(market/1000 · multiplier + margin + excise) · (1 + VAT)``.
* **distribution price** – variable distribution charge (net, configurable).
* **all-in marginal price** – energy price + variable distribution (gross) when
  the Pstryk price does not already include distribution.

The prosumer sell price follows the formula documented by Pstryk for
``energy_sold_value``: ``max(tge_price, 0) · (1 + VAT)``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from .const import LOCAL_TZ
from .forecasting.features import is_holiday
from .models.price_slot import PriceSlot

TZ = ZoneInfo(LOCAL_TZ)

DIST_NONE = "none"  # flat variable distribution rate
DIST_G11 = "G11"
DIST_G12 = "G12"
DIST_G12W = "G12w"
DIST_G13 = "G13"
DIST_TARIFFS = [DIST_NONE, DIST_G11, DIST_G12, DIST_G12W, DIST_G13]

# Typical zone hours (local time) – operators differ, so every value is editable in the options.
DEFAULT_OFFPEAK_HOURS = {DIST_G12: "22-6,13-15", DIST_G12W: "22-6,13-15", DIST_G13: "21-7,13-16"}
DEFAULT_PEAK2_HOURS = {DIST_G13: "16-21"}


def parse_hour_ranges(text: str | None) -> set[int]:
    """``"22-6,13-15"`` -> {22, 23, 0, ..., 5, 13, 14} (end hour exclusive)."""
    hours: set[int] = set()
    for part in str(text or "").replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        a, sep, b = part.partition("-")
        try:
            start = int(a) % 24
            end = int(b) % 24 if sep else (start + 1) % 24
        except ValueError:
            continue
        h = start
        for _ in range(24):
            if h == end and (h != start or _ > 0):
                break
            hours.add(h)
            h = (h + 1) % 24
            if h == end:
                break
    return hours


@dataclass(slots=True)
class DistributionTariff:
    """Time-of-use variable distribution charge (net PLN/kWh)."""

    kind: str = DIST_NONE
    rate_peak: float = 0.0  # G11: the only rate; G12/G12w: day; G13: morning peak
    rate_offpeak: float = 0.0  # G12/G12w/G13 off-peak
    rate_peak2: float = 0.0  # G13 afternoon peak
    offpeak_hours: set[int] = field(default_factory=set)
    peak2_hours: set[int] = field(default_factory=set)
    weekend_offpeak: bool = False  # G12w / G13: weekends and holidays are off-peak

    def zone(self, at: datetime) -> str:
        if self.kind in (DIST_NONE, DIST_G11):
            return "flat"
        local = at.astimezone(TZ)
        if self.weekend_offpeak and (local.weekday() >= 5 or is_holiday(local.date())):
            return "offpeak"
        if local.hour in self.offpeak_hours:
            return "offpeak"
        if self.kind == DIST_G13 and local.hour in self.peak2_hours:
            return "peak2"
        return "peak"

    def rate(self, at: datetime) -> float:
        z = self.zone(at)
        if z == "offpeak":
            return self.rate_offpeak
        if z == "peak2":
            return self.rate_peak2
        return self.rate_peak


@dataclass(slots=True)
class Tariff:
    vat_rate: float = 0.23
    energy_margin_net: float = 0.0  # PLN/kWh
    excise_net: float = 0.005  # PLN/kWh (akcyza)
    var_distribution_net: float = 0.0  # PLN/kWh
    pstryk_includes_distribution: bool = False
    multiplier: float = 1.0
    calibrated_offset: float | None = None  # PLN/kWh gross, replaces margin+excise when set
    calibration_samples: int = 0
    distribution: DistributionTariff | None = None  # time-of-use distribution (G12/G13…)

    def energy_price(self, market_pln_mwh: float) -> float:
        """Estimated gross energy price (comparable with Pstryk ``price_gross``)."""
        base = market_pln_mwh / 1000.0 * self.multiplier
        if self.calibrated_offset is not None:
            return base * (1 + self.vat_rate) + self.calibrated_offset
        return (base + self.energy_margin_net + self.excise_net) * (1 + self.vat_rate)

    def distribution_gross(self, at: datetime | None = None) -> float:
        """Variable distribution charge (gross); time-of-use when a zone tariff is set."""
        if self.distribution is not None and self.distribution.kind != DIST_NONE and at is not None:
            return self.distribution.rate(at) * (1 + self.vat_rate)
        return self.var_distribution_net * (1 + self.vat_rate)

    def distribution_zone(self, at: datetime) -> str:
        if self.distribution is None or self.distribution.kind == DIST_NONE:
            return "flat"
        return self.distribution.zone(at)

    def all_in(self, energy_price_gross: float, at: datetime | None = None) -> float:
        if self.pstryk_includes_distribution:
            return energy_price_gross
        return energy_price_gross + self.distribution_gross(at)

    def all_in_slots(self, slots: list[PriceSlot]) -> list[PriceSlot]:
        """Copy of ``slots`` with the variable distribution charge added (for optimisation)."""
        if self.pstryk_includes_distribution:
            return slots
        out = []
        for s in slots:
            if s.value is None:
                out.append(s)
                continue
            d = self.distribution_gross(s.start)
            out.append(
                replace(
                    s,
                    value=s.value + d,
                    p10=None if s.p10 is None else s.p10 + d,
                    p50=None if s.p50 is None else s.p50 + d,
                    p90=None if s.p90 is None else s.p90 + d,
                    meta={**s.meta, "distribution_gross": round(d, 5)},
                )
            )
        return out

    def sell_price(self, market_pln_mwh: float) -> float:
        return max(market_pln_mwh, 0.0) / 1000.0 * (1 + self.vat_rate)

    def calibrate(self, pairs: list[tuple[float, float]], min_samples: int = 48) -> bool:
        """Fit ``pstryk = a·market·(1+VAT)/1000 + b`` on overlapping hours.

        Local, private use only (opt-in). Returns True when parameters changed.
        """
        if len(pairs) < min_samples:
            return False
        xs = [m / 1000.0 * (1 + self.vat_rate) for m, _ in pairs]
        ys = [p for _, p in pairs]
        n = len(xs)
        mx = sum(xs) / n
        my = sum(ys) / n
        sxx = sum((x - mx) ** 2 for x in xs)
        if sxx <= 1e-9:
            return False
        a = sum((x - mx) * (y - my) for x, y in zip(xs, ys, strict=True)) / sxx
        if not 0.5 <= a <= 1.5:
            return False  # implausible — keep configured tariff
        self.multiplier = a
        self.calibrated_offset = my - a * mx
        self.calibration_samples = n
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "vat_rate": self.vat_rate,
            "energy_margin_net": self.energy_margin_net,
            "excise_net": self.excise_net,
            "var_distribution_net": self.var_distribution_net,
            "pstryk_includes_distribution": self.pstryk_includes_distribution,
            "multiplier": round(self.multiplier, 5),
            "calibrated_offset": None if self.calibrated_offset is None else round(self.calibrated_offset, 5),
            "calibration_samples": self.calibration_samples,
            "distribution": None
            if self.distribution is None
            else {
                "kind": self.distribution.kind,
                "rate_peak": self.distribution.rate_peak,
                "rate_offpeak": self.distribution.rate_offpeak,
                "rate_peak2": self.distribution.rate_peak2,
                "offpeak_hours": sorted(self.distribution.offpeak_hours),
                "peak2_hours": sorted(self.distribution.peak2_hours),
                "weekend_offpeak": self.distribution.weekend_offpeak,
            },
        }


def calibration_pairs(pstryk: dict[datetime, float], market: dict[datetime, float]) -> list[tuple[float, float]]:
    return [(market[h], v) for h, v in pstryk.items() if h in market]
