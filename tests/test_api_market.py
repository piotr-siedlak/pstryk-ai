"""ENTSO-E, PSE, TGE and Open-Meteo parsing."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.pstryk_ai.api.base import ProviderAuthError
from custom_components.pstryk_ai.api.entsoe import parse_price_document
from custom_components.pstryk_ai.api.pse import parse_his_wlk_cal, parse_pk5l, parse_rce
from custom_components.pstryk_ai.api.tge import parse_rdn_html
from custom_components.pstryk_ai.api.weather import REGIONS, build_national, parse_local, wind_power_index
from custom_components.pstryk_ai.models.price_slot import MarketPoint, aggregate_hourly, mwh_to_kwh

from .conftest import load_fixture, load_json


def test_entsoe_quarter_hour_a03_and_currency() -> None:
    points = parse_price_document(load_fixture("entsoe_a44_pl.xml"), eur_pln=4.0)
    quarters = [p for p in points if p.product == "quarter_hour"]
    hourly = [p for p in points if p.product == "hourly"]
    assert [p.price_pln_mwh for p in quarters] == [400.0, 420.0, 420.0, -15.5]  # A03 repeats position 2
    assert [p.price_pln_mwh for p in hourly] == [400.0, 0.0]  # EUR converted with 4.0
    assert quarters[0].start == datetime(2026, 10, 15, 22, tzinfo=UTC)


def test_entsoe_no_data_and_auth() -> None:
    assert parse_price_document(load_fixture("entsoe_no_data.xml"), 4.25) == []
    bad = load_fixture("entsoe_no_data.xml").replace(
        "No matching data found for Data item Day-ahead Prices [12.1.D]", "User is not authorized (invalid token)"
    )
    with pytest.raises(ProviderAuthError):
        parse_price_document(bad, 4.25)


def test_hourly_aggregation_requires_four_quarters() -> None:
    t0 = datetime(2026, 10, 16, 0, tzinfo=UTC)
    pts = [
        MarketPoint(
            t0 + timedelta(minutes=15 * i), t0 + timedelta(minutes=15 * (i + 1)), 100.0 + i, "x", "quarter_hour"
        )
        for i in range(7)
    ]
    hourly = aggregate_hourly(pts)
    assert hourly == {t0: pytest.approx(101.5)}  # second hour incomplete -> dropped
    # hourly product wins over quarter-derived values
    pts.append(MarketPoint(t0, t0 + timedelta(hours=1), 999.0, "x", "hourly"))
    assert aggregate_hourly(pts)[t0] == 999.0


def test_mwh_conversion() -> None:
    assert mwh_to_kwh(650.0) == pytest.approx(0.65)
    assert mwh_to_kwh(-20.0) == pytest.approx(-0.02)


def test_pse_pk5l_real_sample() -> None:
    rows = parse_pk5l(load_json("pse_pk5l.json")["value"])
    assert len(rows) == 24
    first = rows[0]
    assert first.demand_mw and first.demand_mw > 5000
    assert first.residual_mw == pytest.approx(first.demand_mw - (first.wind_mw or 0) - (first.pv_mw or 0))
    # plan_dtime marks the end of the hour
    assert (rows[1].start - rows[0].start) == timedelta(hours=1)


def test_pse_rce_is_separate_dataset() -> None:
    pts = parse_rce(load_json("pse_rce.json")["value"])
    assert len(pts) == 96
    assert {p.provider for p in pts} == {"pse_rce"}
    assert all(p.product == "quarter_hour" for p in pts)
    hourly = aggregate_hourly(pts)
    assert len(hourly) == 24


def test_pse_realised_generation_complete_hours_only() -> None:
    rows = [{"dtime_utc": f"2026-10-14 22:{m:02d}:00", "demand": 16000, "wi": 4000, "pv": 0} for m in (15, 30, 45)] + [
        {"dtime_utc": "2026-10-14 23:00:00", "demand": 16100, "wi": 4100, "pv": 0}
    ]
    out = parse_his_wlk_cal(rows)
    assert len(out) == 1
    assert out[0].demand_mw == pytest.approx(16025)


def test_tge_html_parser_fixing_one_and_quarters() -> None:
    points = parse_rdn_html(load_fixture("tge_rdn_sample.html"))
    hourly = [p for p in points if p.product == "hourly"]
    quarter = [p for p in points if p.product == "quarter_hour"]
    assert [p.price_pln_mwh for p in hourly] == [672.26, -12.5]
    assert hourly[0].start == datetime(2026, 10, 16, 22, tzinfo=UTC)  # 00:00 local (CEST)
    assert [p.price_pln_mwh for p in quarter] == [725.96, 668.49]
    assert quarter[0].start == datetime(2026, 10, 16, 22, tzinfo=UTC)
    fii = parse_rdn_html(load_fixture("tge_rdn_sample.html"), fixing="II")
    assert [p.price_pln_mwh for p in fii if p.product == "hourly"] == [735.11]


def test_open_meteo_local_real_sample() -> None:
    hours = parse_local(load_json("openmeteo_local.json"))
    assert len(hours) == 48
    assert hours[0].start.tzinfo is UTC
    assert "wind_speed_120m" in hours[0].values


def test_national_weather_aggregation_with_models() -> None:
    times = ["2026-10-16T00:00", "2026-10-16T01:00"]
    items = []
    for _ in REGIONS:
        hourly = {"time": times}
        for m, speed in (("ecmwf_ifs025", 8.0), ("icon_seamless", 10.0)):
            hourly[f"temperature_2m_{m}"] = [5.0, 6.0]
            hourly[f"wind_speed_100m_{m}"] = [speed, speed]
            hourly[f"shortwave_radiation_{m}"] = [0.0, 50.0]
            hourly[f"cloud_cover_{m}"] = [50, 60]
        items.append({"hourly": hourly})
    out = build_national(items, models=["ecmwf_ifs025", "icon_seamless"])
    assert len(out) == 2
    assert out[0].get("national_temperature") == pytest.approx(5.0)
    assert out[0].get("national_hdd") == pytest.approx(13.0)
    assert out[0].get("national_wind_index") == pytest.approx(wind_power_index(9.0), rel=0.2)
    assert out[0].get("wind_model_spread") > 0


def test_wind_power_curve() -> None:
    assert wind_power_index(2.0) == 0
    assert wind_power_index(12.0) == 1
    assert wind_power_index(30.0) == 0
    assert 0 < wind_power_index(7.0) < 1
