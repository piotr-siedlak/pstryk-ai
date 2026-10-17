"""Device-profile scheduler (dynamic programming over hourly slots).

Constraints: required hours, minimum run time, minimum off time, allowed daily
operating window, earliest start, deadline and maximum acceptable price. The
whole planning window is optimised jointly (not day by day).
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, time, timedelta
import math
from zoneinfo import ZoneInfo

from ..const import LOCAL_TZ
from ..models.optimizer import DeviceProfile, DeviceSchedule
from ..models.price_slot import PriceSlot
from .cheapest_hours import best_window, effective_price

TZ = ZoneInfo(LOCAL_TZ)


def _in_daily_window(moment: datetime, start: time | None, end: time | None) -> bool:
    if start is None or end is None or start == end:
        return True
    local = moment.astimezone(TZ).time()
    if start < end:
        return start <= local < end
    return local >= start or local < end  # window across midnight


def schedule_device(
    profile: DeviceProfile,
    slots: Sequence[PriceSlot],
    now: datetime,
    *,
    risk_aversion: float = 0.0,
    default_horizon_h: int = 24,
    max_speculative_hours: int | None = None,
    current_value: float | None = None,
) -> DeviceSchedule:
    result = _schedule_device(
        profile,
        slots,
        now,
        risk_aversion=risk_aversion,
        default_horizon_h=default_horizon_h,
        max_speculative_hours=max_speculative_hours,
        current_value=current_value,
    )
    result.current_value = current_value
    result.target = profile.target
    return result


def _schedule_device(
    profile: DeviceProfile,
    slots: Sequence[PriceSlot],
    now: datetime,
    *,
    risk_aversion: float,
    default_horizon_h: int,
    max_speculative_hours: int | None,
    current_value: float | None,
) -> DeviceSchedule:
    if profile.enabled and profile.target is not None and current_value is not None and current_value >= profile.target:
        return DeviceSchedule(
            profile.name,
            [],
            0.0,
            0.0,
            True,
            f"Cel osiągnięty ({current_value:.1f} ≥ {profile.target:.1f}) – praca niepotrzebna",
        )
    if profile.enabled and profile.temperature_topic and profile.target is not None and current_value is None:
        reason_suffix = " (brak aktualnego odczytu MQTT – plan bez uwzględnienia celu)"
    else:
        reason_suffix = ""
    required = profile.required_hours
    earliest = max(now, profile.earliest_start) if profile.earliest_start else now
    deadline = profile.deadline or (now + timedelta(hours=default_horizon_h))
    cand = [
        s
        for s in slots
        if s.start >= earliest.replace(minute=0, second=0, microsecond=0) and s.end <= deadline and s.end > now
    ]
    if not profile.enabled:
        return DeviceSchedule(profile.name, [], None, 0.0, False, "Profil wyłączony")

    allowed: list[bool] = []
    prices: list[float] = []
    for s in cand:
        eff = effective_price(s, risk_aversion)
        ok = eff is not None and _in_daily_window(s.start, profile.allowed_start, profile.allowed_end)
        if ok and profile.max_price is not None and s.value is not None and s.value > profile.max_price:
            ok = False
        allowed.append(ok)
        prices.append(eff if eff is not None else math.inf)

    if not cand or not any(allowed):
        if any(s.value is None for s in cand) or not cand:
            # Fallback: no prices — start as early as allowed so the task completes.
            fallback = [s.start for s in cand if _in_daily_window(s.start, profile.allowed_start, profile.allowed_end)][
                :required
            ]
            return DeviceSchedule(
                profile.name,
                fallback,
                None,
                required * profile.power_kw,
                bool(fallback),
                "Brak cen – harmonogram awaryjny (najwcześniejszy możliwy start)",
                fallback[0] if fallback else None,
                (fallback[-1] + timedelta(hours=1)) if fallback else None,
            )
        return DeviceSchedule(profile.name, [], None, 0.0, False, "Brak dozwolonych godzin w oknie")

    if profile.consecutive:
        usable = [s for s, ok in zip(cand, allowed, strict=True) if ok]
        win = best_window(
            usable,
            required,
            now=now,
            risk_aversion=risk_aversion,
            max_speculative_hours=max_speculative_hours,
        )
        if win is None:
            return DeviceSchedule(profile.name, [], None, 0.0, False, "Brak ciągłego okna o wymaganej długości")
        chosen = win.slots
    else:
        chosen = _dp(cand, allowed, prices, required, max(1, profile.min_run_h), max(0, profile.min_off_h))
        if chosen is None:
            return DeviceSchedule(profile.name, [], None, 0.0, False, "Ograniczenia niewykonalne przed terminem")

    by_start = {s.start: s for s in cand}
    cost = sum((by_start[t].value or 0.0) * profile.power_kw for t in chosen)
    first_block_end = chosen[0] + timedelta(hours=1)
    for t in chosen[1:]:
        if t != first_block_end:
            break
        first_block_end = t + timedelta(hours=1)
    return DeviceSchedule(
        profile=profile.name,
        slots=chosen,
        expected_cost=cost,
        expected_energy_kwh=len(chosen) * profile.power_kw,
        feasible=True,
        reason="Optymalny harmonogram w oknie planowania" + reason_suffix,
        next_start=chosen[0],
        next_stop=first_block_end,
    )


def _dp(
    slots: list[PriceSlot],
    allowed: list[bool],
    prices: list[float],
    required: int,
    min_run: int,
    min_off: int,
) -> list[datetime] | None:
    """Minimise cost subject to run/off constraints. Returns selected starts."""
    n = len(slots)
    min_run = min(min_run, required)
    # state: (done, mode, length) ; mode 1=on (length capped at min_run), 0=off (capped at min_off)
    start_state = (0, 0, min_off)  # assume the device has been off long enough
    layer: dict[tuple[int, int, int], tuple[float, tuple | None]] = {start_state: (0.0, None)}
    history: list[dict[tuple[int, int, int], tuple[float, tuple | None]]] = []
    for i in range(n):
        nxt: dict[tuple[int, int, int], tuple[float, tuple | None]] = {}
        contiguous = i == 0 or slots[i - 1].end == slots[i].start
        for state, (cost, _) in layer.items():
            done, mode, length = state
            if not contiguous:
                # gap in slots: an active run is broken
                if mode == 1 and length < min_run:
                    continue
                mode, length = 0, min_off
            # option OFF
            if not (mode == 1 and length < min_run):
                new_len = min(min_off, length + 1) if mode == 0 else 1 if min_off else 0
                key = (done, 0, new_len if min_off else 0)
                if key not in nxt or cost < nxt[key][0]:
                    nxt[key] = (cost, (state, 0))
            # option ON
            if allowed[i] and done < required and not (mode == 0 and length < min_off):
                new_len = min(min_run, length + 1) if mode == 1 else 1
                key = (done + 1, 1, new_len)
                c = cost + prices[i]
                if key not in nxt or c < nxt[key][0]:
                    nxt[key] = (c, (state, 1))
        history.append(nxt)
        layer = nxt
    finals = [(c, s) for s, (c, _) in layer.items() if s[0] == required and not (s[1] == 1 and s[2] < min_run)]
    if not finals:
        return None
    _, state = min(finals)
    chosen: list[datetime] = []
    for i in range(n - 1, -1, -1):
        cost, back = history[i][state]
        prev_state, action = back  # type: ignore[misc]
        if action == 1:
            chosen.append(slots[i].start)
        state = prev_state
    return sorted(chosen)
