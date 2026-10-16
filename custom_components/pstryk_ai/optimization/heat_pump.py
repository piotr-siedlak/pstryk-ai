"""Heat pump COP model.

COP(T_out, T_supply) is estimated from either a user supplied curve of
``outdoor_temp:cop`` points measured at a 35 °C supply temperature, or from a
single nominal COP (A7/W35). The supply-temperature dependency follows the
Carnot ratio, i.e. a fixed fraction of the ideal COP:

    COP_ideal = T_supply_K / (T_supply_K − T_out_K)

This captures the key effect that a hotter buffer lowers the COP, so heating
"more and earlier" is not automatically cheaper.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import itertools

KELVIN = 273.15
NOMINAL_OUT = 7.0
NOMINAL_SUPPLY = 35.0
MIN_LIFT = 5.0


def parse_cop_curve(text: str | None) -> list[tuple[float, float]]:
    """Parse ``"-15:2.0, -7:2.6, 2:3.3, 7:4.1"`` into sorted points."""
    if not text:
        return []
    points = []
    for part in str(text).replace(";", ",").split(","):
        if ":" not in part:
            continue
        t, c = part.split(":", 1)
        try:
            points.append((float(t), float(c)))
        except ValueError:
            continue
    return sorted(points)


def _carnot(t_out: float, t_supply: float) -> float:
    lift = max(MIN_LIFT, t_supply - t_out)
    return (t_supply + KELVIN) / lift


@dataclass(slots=True)
class CopModel:
    nominal_cop: float = 3.0
    curve: list[tuple[float, float]] = field(default_factory=list)
    min_cop: float = 1.0
    max_cop: float = 7.0
    calibration: float = 1.0  # multiplicative correction learned from measurements

    def _cop_at_35(self, t_out: float) -> float:
        if not self.curve:
            eta = self.nominal_cop / _carnot(NOMINAL_OUT, NOMINAL_SUPPLY)
            return eta * _carnot(t_out, NOMINAL_SUPPLY)
        pts = self.curve
        if t_out <= pts[0][0]:
            return pts[0][1]
        if t_out >= pts[-1][0]:
            return pts[-1][1]
        for (t1, c1), (t2, c2) in itertools.pairwise(pts):
            if t1 <= t_out <= t2:
                return c1 + (c2 - c1) * (t_out - t1) / (t2 - t1)
        return pts[-1][1]

    def cop(self, t_out: float, t_supply: float) -> float:
        base = self._cop_at_35(t_out)
        ratio = _carnot(t_out, t_supply) / _carnot(t_out, NOMINAL_SUPPLY)
        value = base * ratio * self.calibration
        return max(self.min_cop, min(self.max_cop, value))

    def calibrate(self, samples: list[tuple[float, float, float]]) -> None:
        """Update correction from (t_out, t_supply, measured_cop) samples."""
        ratios = [m / self.cop(o, s) * self.calibration for o, s, m in samples if m > 0]
        if len(ratios) >= 10:
            ratios.sort()
            self.calibration = max(0.5, min(1.5, ratios[len(ratios) // 2]))
