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

from dataclasses import dataclass
from datetime import datetime
from typing import Any


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

    def energy_price(self, market_pln_mwh: float) -> float:
        """Estimated gross energy price (comparable with Pstryk ``price_gross``)."""
        base = market_pln_mwh / 1000.0 * self.multiplier
        if self.calibrated_offset is not None:
            return base * (1 + self.vat_rate) + self.calibrated_offset
        return (base + self.energy_margin_net + self.excise_net) * (1 + self.vat_rate)

    def distribution_gross(self) -> float:
        return self.var_distribution_net * (1 + self.vat_rate)

    def all_in(self, energy_price_gross: float) -> float:
        if self.pstryk_includes_distribution:
            return energy_price_gross
        return energy_price_gross + self.distribution_gross()

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
        }


def calibration_pairs(pstryk: dict[datetime, float], market: dict[datetime, float]) -> list[tuple[float, float]]:
    return [(market[h], v) for h, v in pstryk.items() if h in market]
