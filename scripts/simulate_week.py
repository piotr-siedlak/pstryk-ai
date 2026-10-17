"""Simulate 7 days of buffer operation on REAL public data and compare strategies.

Prices: PSE RCE (public, 15-min → hourly) converted to a customer price with the
default tariff (as a stand-in for Pstryk prices, which cannot be fetched without
a key). Outdoor temperature: Open-Meteo (past days) for the given location.

Usage:  python scripts/simulate_week.py [--lat 52.03 --lon 21.05] [--json out.json]
"""

from __future__ import annotations

import argparse
import asyncio
from datetime import date, timedelta
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


async def fetch(lat: float, lon: float, days: int):
    end = date.today()
    start = end - timedelta(days=days + 1)
    async with aiohttp.ClientSession() as s:
        rce = await PseClient(s).rce_prices(start, end)
        weather = await WeatherClient(s, "best_match").local_forecast(lat, lon, days=1)
        hist = await WeatherClient(s).local_historical(lat, lon, start, end - timedelta(days=1)) if days > 5 else []
    return rce, weather, hist


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lat", type=float, default=52.03)
    ap.add_argument("--lon", type=float, default=21.05)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--json", type=str, default="")
    args = ap.parse_args()
    rce, weather, hist = asyncio.run(fetch(args.lat, args.lon, args.days))
    hourly = aggregate_hourly(rce)
    tariff = Tariff()
    prices = [(t, tariff.energy_price(v)) for t, v in sorted(hourly.items())]
    outdoor = {w.start: w.get("temperature_2m") for w in [*hist, *weather] if w.get("temperature_2m") is not None}
    hours = min(24 * args.days, len(prices) - 36)
    cfg = BufferConfig(
        volume_l=500,
        min_t=30,
        max_t=60,
        target_t=35,
        hp_thermal_kw=9,
        hp_electric_kw=3,
        building_kw_per_k=0.25,
        max_horizon_h=48,
        hp_max_t=55,
        hp_levels=hp_levels(30),
    )
    result = compare(prices, outdoor, cfg, CopModel(nominal_cop=3.0), start_t=35, boost_t=55, hours=hours)
    first, last = prices[0][0], prices[hours - 1][0]
    print(f"Real data {first:%Y-%m-%d %H:%M} – {last:%Y-%m-%d %H:%M} UTC ({hours} h)")
    p = [v for _, v in prices[:hours]]
    print(f"Price min/avg/max: {min(p):.3f} / {sum(p) / len(p):.3f} / {max(p):.3f} zł/kWh")
    print(
        f"{'strategy':8} {'cost':>9} {'adj.cost':>9} {'saving':>8} {'kWh el':>8} {'zł/kWh_th':>10} {'<min h':>7} {'starts':>7} {'boost h':>8}"
    )
    for s, r in result.items():
        print(
            f"{s:8} {r['cost_pln']:9.2f} {r['end_heat_adjusted_cost_pln']:9.2f} {r['saving_vs_auto_pln']:8.2f} "
            f"{r['electric_kwh']:8.1f} {r['avg_cost_per_kwh_heat']:10.4f} {r['hours_below_min']:7d} {r['hp_starts']:7d} {r['boost_hours']:8d}"
        )
    if args.json:
        Path(args.json).write_text(
            json.dumps({"from": first.isoformat(), "to": last.isoformat(), "result": result}, indent=1)
        )


if __name__ == "__main__":
    main()
