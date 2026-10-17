"""Cheapest / most-expensive period search over a price timeline.

Works on the full planning window (not per calendar day), so windows may span
midnight or several days. Forecast slots are evaluated with a risk-adjusted
price ``p50 + risk·(p90 − p50)`` and windows that start far in the speculative
future are chosen only when they beat the near-term best by more than the
forecast uncertainty.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
import math

from ..models.optimizer import Window
from ..models.price_slot import PriceSlot


def effective_price(slot: PriceSlot, risk_aversion: float = 0.0) -> float | None:
    if slot.value is None:
        return None
    if slot.source.is_forecast and slot.p90 is not None and slot.p50 is not None:
        return slot.p50 + risk_aversion * max(0.0, slot.p90 - slot.p50)
    return slot.value


def _uncertainty(slot: PriceSlot) -> float:
    if slot.source.is_forecast and slot.p90 is not None and slot.p10 is not None:
        return max(0.0, slot.p90 - slot.p10) / 2
    return 0.0


def filter_slots(
    slots: Sequence[PriceSlot],
    earliest: datetime | None = None,
    deadline: datetime | None = None,
) -> list[PriceSlot]:
    out = []
    for s in slots:
        if s.value is None:
            continue
        if earliest is not None and s.end <= earliest:
            continue
        if deadline is not None and s.end > deadline:
            continue
        out.append(s)
    return out


def _contiguous_runs(slots: list[PriceSlot]) -> list[list[PriceSlot]]:
    runs: list[list[PriceSlot]] = []
    for s in slots:
        if runs and runs[-1][-1].end == s.start:
            runs[-1].append(s)
        else:
            runs.append([s])
    return runs


def _window(chosen: list[PriceSlot]) -> Window:
    values = [s.value for s in chosen if s.value is not None]
    confirmed = sum(1 for s in chosen if s.source.is_confirmed)
    return Window(
        start=chosen[0].start,
        end=chosen[-1].end,
        average_price=sum(values) / len(values),
        total_cost=sum(s.value * s.hours for s in chosen if s.value is not None),
        slots=[s.start for s in chosen],
        confirmed_share=confirmed / len(chosen),
    )


def best_window(
    slots: Sequence[PriceSlot],
    hours: int,
    *,
    now: datetime | None = None,
    earliest: datetime | None = None,
    deadline: datetime | None = None,
    risk_aversion: float = 0.0,
    max_speculative_hours: int | None = None,
    most_expensive: bool = False,
) -> Window | None:
    """Best contiguous window of ``hours`` hourly slots."""
    if hours < 1:
        return None
    cand = filter_slots(slots, earliest or now, deadline)
    best: tuple[float, list[PriceSlot]] | None = None
    near: tuple[float, list[PriceSlot]] | None = None
    limit = now + timedelta(hours=max_speculative_hours) if (now and max_speculative_hours) else None
    sign = -1.0 if most_expensive else 1.0
    for run in _contiguous_runs(cand):
        for i in range(len(run) - hours + 1):
            chunk = run[i : i + hours]
            eff = [effective_price(s, 0.0 if most_expensive else risk_aversion) for s in chunk]
            if any(e is None for e in eff):
                continue
            score = sign * sum(eff) / hours  # type: ignore[arg-type]
            if best is None or score < best[0]:
                best = (score, chunk)
            if limit is not None and chunk[0].start < limit and (near is None or score < near[0]):
                near = (score, chunk)
    if best is None:
        return None
    if near is not None and near[1] is not best[1] and not most_expensive:
        margin = sum(_uncertainty(s) for s in best[1]) / hours
        if best[0] + margin >= near[0]:
            best = near
    return _window(best[1])


def cheapest_n(
    slots: Sequence[PriceSlot],
    n: int,
    *,
    now: datetime | None = None,
    earliest: datetime | None = None,
    deadline: datetime | None = None,
    risk_aversion: float = 0.0,
    most_expensive: bool = False,
) -> Window | None:
    """Cheapest (or most expensive) ``n`` hours, not necessarily consecutive."""
    cand = filter_slots(slots, earliest or now, deadline)
    scored = [(effective_price(s, risk_aversion), s) for s in cand]
    scored = [(e, s) for e, s in scored if e is not None]
    if len(scored) < n or n < 1:
        return None
    scored.sort(key=lambda x: (-x[0] if most_expensive else x[0], x[1].start))
    chosen = sorted((s for _, s in scored[:n]), key=lambda s: s.start)
    return _window(chosen)


def percentile(values: list[float], q: float) -> float:
    s = sorted(values)
    if not s:
        return math.nan
    pos = (len(s) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return s[lo] + (s[hi] - s[lo]) * (pos - lo)


def relative_thresholds(
    slots: Sequence[PriceSlot], low_q: float = 0.25, high_q: float = 0.75
) -> tuple[float, float] | None:
    values = [s.value for s in slots if s.value is not None]
    if len(values) < 4:
        return None
    return percentile(values, low_q), percentile(values, high_q)


def classify(
    slot: PriceSlot,
    reference: Sequence[PriceSlot],
    absolute_threshold: float | None = None,
    low_q: float = 0.25,
    high_q: float = 0.75,
) -> dict[str, bool | None]:
    """Cheap/expensive flags; Pstryk's own flags are kept separately."""
    thr = relative_thresholds(reference, low_q, high_q)
    if slot.value is None or thr is None:
        return {"cheap": None, "expensive": None, "below_absolute": None}
    return {
        "cheap": slot.value <= thr[0],
        "expensive": slot.value >= thr[1],
        "below_absolute": None if absolute_threshold is None else slot.value <= absolute_threshold,
    }
