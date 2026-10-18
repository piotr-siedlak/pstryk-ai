"""Benchmark the heating strategies on three real 4-week periods (winter, spring, autumn).

For each period: heat pump alone, boost only, full control (all closed-loop, prices
known only as they would be live) and the perfect-foresight optimum (lower bound).
Data: PSE RCE prices with the default tariff (stand-in for Pstryk prices) and the
Open-Meteo archive temperature; downloaded once and cached.

Usage:  python scripts/benchmark_heating.py [--curve 0.4] [--hp-minus15 6.5] [--cache DIR]
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime, timedelta
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import aiohttp

from custom_components.pstryk_ai.api.pse import PseClient
from custom_components.pstryk_ai.api.weather import WeatherClient
from custom_components.pstryk_ai.models.price_slot import aggregate_hourly
from custom_components.pstryk_ai.optimization.heat_pump import CopModel
from custom_components.pstryk_ai.optimization.simulation import compare
from custom_components.pstryk_ai.optimization.thermal_storage import BufferConfig
from custom_components.pstryk_ai.settings_ext import hp_levels
from custom_components.pstryk_ai.tariff import Tariff

PERIODS = {
    "winter": (date(2026, 1, 5), date(2026, 2, 2)),
    "spring": (date(2026, 3, 16), date(2026, 4, 13)),
    "autumn": (date(2026, 9, 14), date(2026, 10, 12)),
}


async def fetch(name: str, lat: float, lon: float, cache: Path) -> dict:
    path = cache / f"{name}_{lat:.2f}_{lon:.2f}.json"
    if path.exists():
        return json.loads(path.read_text())
    first, last = PERIODS[name]
    async with aiohttp.ClientSession() as s:
        rce = []
        day = first
        while day <= last:
            end = min(last, day + timedelta(days=6))
            rce += await PseClient(s).rce_prices(day, end)
            day = end + timedelta(days=1)
        weather = await WeatherClient(s).local_historical(lat, lon, first - timedelta(days=1), last + timedelta(days=1))
    data = {
        "prices": [[k.isoformat(), v] for k, v in sorted(aggregate_hourly(rce).items())],
        "temps": [
            [w.start.isoformat(), w.get("temperature_2m")] for w in weather if w.get("temperature_2m") is not None
        ],
    }
    cache.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return data


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lat", type=float, default=52.03)
    ap.add_argument("--lon", type=float, default=21.05)
    ap.add_argument("--curve", type=float, default=0.0, help="heating curve slope (K per K below 0 °C)")
    ap.add_argument("--hp-minus15", type=float, default=None, help="heat pump output at −15 °C, kW")
    ap.add_argument("--days", type=int, default=27)
    ap.add_argument("--cache", type=Path, default=Path.home() / ".cache" / "pstryk_ai_bench")
    ap.add_argument("--json", type=str, default="")
    args = ap.parse_args()
    tariff = Tariff()
    cfg = BufferConfig(
        volume_l=500, min_t=30, max_t=60, target_t=35, hp_thermal_kw=9, hp_electric_kw=3,
        building_kw_per_k=0.2, max_horizon_h=48, hp_max_t=55, hp_levels=hp_levels(30),
        curve_slope=args.curve, hp_kw_at_minus15=args.hp_minus15,
    )  # fmt: skip
    cop = CopModel(nominal_cop=3.0)
    report = {}
    head = f"{'':8} {'strategy':8} {'cost zł':>9} {'adj. zł':>9} {'vs alone':>9} {'<min h':>7} {'starts':>7} {'boost h':>8}"
    print(head)
    for name in PERIODS:
        data = asyncio.run(fetch(name, args.lat, args.lon, args.cache))
        prices = [(datetime.fromisoformat(k), tariff.energy_price(v)) for k, v in data["prices"]]
        temps = {datetime.fromisoformat(k): v for k, v in data["temps"]}
        hours = min(24 * args.days, len(prices) - 36)
        res = compare(prices, temps, cfg, cop, start_t=35, boost_t=55, hours=hours, bound=True)
        report[name] = res
        for s, r in res.items():
            pct = r["saving_vs_auto_pln"] / res["auto"]["cost_pln"] * 100 if res["auto"]["cost_pln"] else 0.0
            print(
                f"{name:8} {s:8} {r['cost_pln']:9.2f} {r['end_heat_adjusted_cost_pln']:9.2f} {pct:8.1f}% "
                f"{r['hours_below_min']:7d} {r['hp_starts']:7d} {r['boost_hours']:8d}"
            )
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
