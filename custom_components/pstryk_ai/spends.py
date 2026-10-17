"""Pstryk spending summaries (daily, monthly, 12 months) from unified-metrics frames.

Cost fields used by Pstryk's ``cost`` metric (see docs/API_SOURCES.md):
``energy_import_cost`` (gross import cost), ``energy_sold_value`` (gross value of
exported energy), ``energy_balance_value`` and the breakdown ``energy_cost_net``,
``var_dist_cost_net``, ``fix_dist_cost_net``, ``service_cost_net``,
``power_fee_cost_net``, ``excise``, ``vat``. Every field is optional – only what
the API returns is summed.
"""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from .const import LOCAL_TZ
from .models.energy_data import MeterFrame

TZ = ZoneInfo(LOCAL_TZ)

BREAKDOWN_FIELDS = (
    "energy_cost_net",
    "var_dist_cost_net",
    "fix_dist_cost_net",
    "service_cost_net",
    "power_fee_cost_net",
    "excise",
    "vat",
)


def _f(value: Any) -> float | None:
    try:
        return None if value is None else float(value)
    except (TypeError, ValueError):
        return None


@dataclass(slots=True)
class PeriodTotals:
    key: str  # YYYY-MM-DD or YYYY-MM
    import_kwh: float | None = None
    export_kwh: float | None = None
    cost: float | None = None
    sold: float | None = None
    balance: float | None = None
    breakdown: dict[str, float] = field(default_factory=dict)
    live: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "period": self.key,
            "import_kwh": _r(self.import_kwh),
            "export_kwh": _r(self.export_kwh),
            "cost": _r(self.cost, 2),
            "sold": _r(self.sold, 2),
            "balance": _r(self.balance, 2),
            "breakdown": {k: round(v, 2) for k, v in self.breakdown.items()},
            "live": self.live,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PeriodTotals:
        return cls(
            key=data["period"],
            import_kwh=data.get("import_kwh"),
            export_kwh=data.get("export_kwh"),
            cost=data.get("cost"),
            sold=data.get("sold"),
            balance=data.get("balance"),
            breakdown=dict(data.get("breakdown") or {}),
            live=bool(data.get("live")),
        )


def _r(v: float | None, d: int = 3) -> float | None:
    return None if v is None else round(v, d)


def frame_totals(frame: MeterFrame, key: str) -> PeriodTotals:
    breakdown = {k: v for k in BREAKDOWN_FIELDS if (v := _f(frame.cost.get(k))) is not None}
    return PeriodTotals(
        key=key,
        import_kwh=frame.import_kwh,
        export_kwh=frame.export_kwh,
        cost=frame.import_cost,
        sold=frame.sold_value,
        balance=frame.balance_value,
        breakdown=breakdown,
        live=frame.is_live,
    )


def daily_totals(frames: list[MeterFrame]) -> dict[str, PeriodTotals]:
    """Daily frames (aggregated for Europe/Warsaw) keyed by local date."""
    out = {}
    for f in frames:
        # frames are aligned to local midnight; take the local date of the middle of the frame
        mid = f.start + (f.end - f.start) / 2
        key = mid.astimezone(TZ).date().isoformat()
        out[key] = frame_totals(f, key)
    return out


def monthly_totals(frames: list[MeterFrame]) -> dict[str, PeriodTotals]:
    out = {}
    for f in frames:
        mid = f.start + (f.end - f.start) / 2
        key = mid.astimezone(TZ).strftime("%Y-%m")
        out[key] = frame_totals(f, key)
    return out


def _sum(items: list[PeriodTotals], attr: str) -> float | None:
    vals = [getattr(i, attr) for i in items if getattr(i, attr) is not None]
    return round(sum(vals), 4) if vals else None


@dataclass
class SpendsSummary:
    today: PeriodTotals | None
    yesterday: PeriodTotals | None
    this_month: dict[str, float | None]
    previous_month: dict[str, float | None]
    last_12_months: dict[str, float | None]
    avg_daily_cost: float | None
    projected_month_cost: float | None
    breakdown_month: dict[str, float]
    days: list[dict[str, Any]]
    months: list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "today": self.today.to_dict() if self.today else None,
            "yesterday": self.yesterday.to_dict() if self.yesterday else None,
            "this_month": self.this_month,
            "previous_month": self.previous_month,
            "last_12_months": self.last_12_months,
            "avg_daily_cost": self.avg_daily_cost,
            "projected_month_cost": self.projected_month_cost,
            "breakdown_month": self.breakdown_month,
        }


def _totals(items: list[PeriodTotals]) -> dict[str, float | None]:
    return {
        "import_kwh": _sum(items, "import_kwh"),
        "export_kwh": _sum(items, "export_kwh"),
        "cost": _sum(items, "cost"),
        "sold": _sum(items, "sold"),
        "balance": _sum(items, "balance"),
    }


def summarize(days: dict[str, PeriodTotals], months: dict[str, PeriodTotals], now: datetime) -> SpendsSummary:
    local = now.astimezone(TZ).date()
    today_key = local.isoformat()
    yesterday_key = (local - timedelta(days=1)).isoformat()
    month_prefix = local.strftime("%Y-%m")
    prev_month_last = local.replace(day=1) - timedelta(days=1)
    prev_prefix = prev_month_last.strftime("%Y-%m")

    month_days = [d for k, d in sorted(days.items()) if k.startswith(month_prefix)]
    prev_days = [d for k, d in sorted(days.items()) if k.startswith(prev_prefix)]
    this_month = _totals(month_days)
    previous = months.get(prev_prefix)
    previous_month = (
        {k: _r(getattr(previous, k), 3) for k in ("import_kwh", "export_kwh", "cost", "sold", "balance")}
        if previous is not None
        else _totals(prev_days)
    )
    # 12 full months before the current one (from monthly frames)
    keys = []
    first = date(local.year, local.month, 1)
    for i in range(1, 13):
        y, m = first.year, first.month - i
        while m <= 0:
            m += 12
            y -= 1
        keys.append(f"{y:04d}-{m:02d}")
    last12 = [months[k] for k in keys if k in months]
    complete = [d for d in month_days if not d.live and d.cost is not None]
    avg = round(sum(d.cost for d in complete) / len(complete), 3) if complete else None  # type: ignore[misc]
    days_in_month = monthrange(local.year, local.month)[1]
    projected = None
    if avg is not None:
        done = sum(d.cost for d in month_days if d.cost is not None)
        remaining = days_in_month - len(complete) - (1 if days.get(today_key) else 0)
        projected = round(done + max(0, remaining) * avg, 2)
    breakdown: dict[str, float] = {}
    for d in month_days:
        for k, v in d.breakdown.items():
            breakdown[k] = round(breakdown.get(k, 0.0) + v, 2)
    return SpendsSummary(
        today=days.get(today_key),
        yesterday=days.get(yesterday_key),
        this_month=this_month,
        previous_month=previous_month,
        last_12_months=_totals(last12) | {"months": len(last12)},
        avg_daily_cost=avg,
        projected_month_cost=projected,
        breakdown_month=breakdown,
        days=[
            d.to_dict() for k, d in sorted(days.items()) if k >= (local.replace(day=1) - timedelta(days=40)).isoformat()
        ],
        months=[m.to_dict() for _, m in sorted(months.items())][-24:],
    )
