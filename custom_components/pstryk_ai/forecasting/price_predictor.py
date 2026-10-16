"""Model B — regularised linear regression (ridge), one model per horizon day.

Why ridge and not gradient boosting inside Home Assistant?

* zero third-party dependencies (pure Python; runs on any HA install incl. ARM),
* training on 12 months × 7 horizons takes seconds in an executor thread,
* deterministic, inspectable coefficients and stable extrapolation,
* incremental normal-equation accumulation makes rolling-origin backtests cheap.

Heavier learners (LightGBM/CatBoost) can be added later as an optional
external service; the core integration must not depend on them.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

MODEL_NAME = "ridge_horizon"
MODEL_VERSION = "1"


def solve_linear(a: list[list[float]], b: list[float]) -> list[float]:
    """Solve ``a x = b`` with Gaussian elimination and partial pivoting."""
    n = len(b)
    m = [[*row[:], b[i]] for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-12:
            raise ValueError("singular matrix")
        m[col], m[pivot] = m[pivot], m[col]
        pv = m[col][col]
        inv = 1.0 / pv
        row_c = m[col]
        for r in range(col + 1, n):
            factor = m[r][col] * inv
            if factor == 0.0:
                continue
            row_r = m[r]
            for c in range(col, n + 1):
                row_r[c] -= factor * row_c[c]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        acc = m[r][n] - sum(m[r][c] * x[c] for c in range(r + 1, n))
        x[r] = acc / m[r][r]
    return x


@dataclass
class NormalEquations:
    """Running sums for standardised ridge regression (supports incremental fit)."""

    dim: int
    count: int = 0
    sum_x: list[float] = field(default_factory=list)
    sum_xx: list[list[float]] = field(default_factory=list)
    sum_xy: list[float] = field(default_factory=list)
    sum_y: float = 0.0
    sum_yy: float = 0.0

    def __post_init__(self) -> None:
        if not self.sum_x:
            self.sum_x = [0.0] * self.dim
            self.sum_xy = [0.0] * self.dim
            self.sum_xx = [[0.0] * self.dim for _ in range(self.dim)]

    def add(self, x: list[float], y: float) -> None:
        self.count += 1
        self.sum_y += y
        self.sum_yy += y * y
        sx, sxy, sxx = self.sum_x, self.sum_xy, self.sum_xx
        for i, xi in enumerate(x):
            if xi == 0.0:
                continue
            sx[i] += xi
            sxy[i] += xi * y
            row = sxx[i]
            for j in range(i, self.dim):
                xj = x[j]
                if xj != 0.0:
                    row[j] += xi * xj

    def solve(self, alpha: float) -> RidgeModel:
        """Fit ridge on standardised features (feature 0 is the bias and skipped)."""
        n = self.count
        if n < self.dim + 5:
            raise ValueError("not enough samples")
        d = self.dim
        mean = [s / n for s in self.sum_x]
        cov = [[0.0] * d for _ in range(d)]
        for i in range(d):
            for j in range(i, d):
                v = self.sum_xx[i][j] / n - mean[i] * mean[j]
                cov[i][j] = cov[j][i] = v
        std = [math.sqrt(max(cov[i][i], 0.0)) or 1.0 for i in range(d)]
        y_mean = self.sum_y / n
        cxy = [self.sum_xy[i] / n - mean[i] * y_mean for i in range(d)]
        idx = [i for i in range(1, d) if cov[i][i] > 1e-12]
        a = [[cov[i][j] / (std[i] * std[j]) + (alpha if i == j else 0.0) for j in idx] for i in idx]
        b = [cxy[i] / std[i] for i in idx]
        beta_std = solve_linear(a, b)
        coef = [0.0] * d
        for k, i in enumerate(idx):
            coef[i] = beta_std[k] / std[i]
        intercept = y_mean - sum(coef[i] * mean[i] for i in range(1, d))
        coef[0] = intercept
        return RidgeModel(coef=coef, alpha=alpha, samples=n)


@dataclass
class RidgeModel:
    coef: list[float]
    alpha: float
    samples: int
    residual_q10: float = -100.0
    residual_q90: float = 100.0
    train_mae: float | None = None

    def predict(self, x: list[float]) -> float:
        return sum(c * v for c, v in zip(self.coef, x, strict=True))

    def to_dict(self) -> dict[str, Any]:
        return {
            "coef": self.coef,
            "alpha": self.alpha,
            "samples": self.samples,
            "residual_q10": self.residual_q10,
            "residual_q90": self.residual_q90,
            "train_mae": self.train_mae,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RidgeModel:
        return cls(
            coef=list(data["coef"]),
            alpha=data.get("alpha", 1.0),
            samples=data.get("samples", 0),
            residual_q10=data.get("residual_q10", -100.0),
            residual_q90=data.get("residual_q90", 100.0),
            train_mae=data.get("train_mae"),
        )


def quantile(values: list[float], q: float) -> float:
    if not values:
        raise ValueError("empty")
    s = sorted(values)
    pos = (len(s) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    if lo == hi:
        return s[lo]
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def fit_ridge(samples: list[tuple[list[float], float]], alpha: float = 1e-3) -> RidgeModel:
    if not samples:
        raise ValueError("no samples")
    ne = NormalEquations(len(samples[0][0]))
    for x, y in samples:
        ne.add(x, y)
    model = ne.solve(alpha)
    residuals = [y - model.predict(x) for x, y in samples]
    model.residual_q10 = quantile(residuals, 0.1)
    model.residual_q90 = quantile(residuals, 0.9)
    model.train_mae = sum(abs(r) for r in residuals) / len(residuals)
    return model
