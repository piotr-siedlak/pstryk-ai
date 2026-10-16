"""Pstryk API client: parsing, placeholders, auth, 429, budget, DST."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import logging

import aiohttp
import pytest
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMocker

from custom_components.pstryk_ai.api.base import (
    ProviderAuthError,
    ProviderRateLimited,
    ProviderUnavailable,
    RequestBudget,
    parse_retry_after,
)
from custom_components.pstryk_ai.api.pstryk import (
    PstrykClient,
    hours_in_local_day,
    is_placeholder_day,
    key_fingerprint,
    local_day_bounds,
    parse_daily,
    parse_hourly,
    shared_budget,
)
from custom_components.pstryk_ai.models.price_slot import PriceSource

from .conftest import local_midnight_utc, pstryk_frames, pstryk_payload


def _now() -> datetime:
    return local_midnight_utc(2026, 10, 16) + timedelta(hours=14)


def test_parse_today_and_tomorrow_confirmed() -> None:
    today = local_midnight_utc(2026, 10, 16)
    frames = pstryk_frames(today, 48, live_index=14)
    snap = parse_hourly(pstryk_payload(frames), _now())
    assert len(snap.buy) == 48
    assert len(snap.sell) == 48
    assert snap.tomorrow_confirmed is True
    assert all(s.source is PriceSource.ACTUAL_PSTRYK for s in snap.buy)
    assert snap.buy[0].meta["net"] == pytest.approx(snap.buy[0].value / 1.23, abs=1e-3)
    assert snap.price_fields == {"buy": True, "sell": True}
    assert snap.hourly[14].is_live
    assert snap.hourly[0].import_kwh == 0.8
    assert snap.hourly[0].import_cost == pytest.approx(0.8 * snap.buy[0].value, abs=1e-3)


def test_placeholder_tomorrow_is_not_confirmed() -> None:
    today = local_midnight_utc(2026, 10, 16)
    frames = pstryk_frames(today, 24) + pstryk_frames(today + timedelta(hours=24), 24, price=0.6)
    snap = parse_hourly(pstryk_payload(frames), _now())
    assert snap.tomorrow_confirmed is False
    assert len(snap.buy) == 24  # placeholder day dropped


def test_partial_tomorrow_not_confirmed_and_missing_prices() -> None:
    today = local_midnight_utc(2026, 10, 16)
    frames = pstryk_frames(today, 24) + pstryk_frames(today + timedelta(hours=24), 10)
    del frames[5]["metrics"]["pricing"]["price_gross"]  # missing interval today
    snap = parse_hourly(pstryk_payload(frames), _now())
    assert snap.tomorrow_confirmed is False
    # today has a missing hour -> not complete; already billed past hours are kept
    assert all(s.start <= _now() for s in snap.buy)


def test_negative_and_zero_prices_are_preserved() -> None:
    today = local_midnight_utc(2026, 10, 16)
    frames = pstryk_frames(today, 24)
    frames[3]["metrics"]["pricing"]["price_gross"] = -0.1234
    frames[4]["metrics"]["pricing"]["price_gross"] = 0.0
    snap = parse_hourly(pstryk_payload(frames), _now())
    values = {s.start.hour: s.value for s in snap.buy}
    assert -0.1234 in values.values()
    assert 0.0 in values.values()


def test_duplicate_timestamps_ignored() -> None:
    today = local_midnight_utc(2026, 10, 16)
    frames = pstryk_frames(today, 24)
    frames.insert(3, dict(frames[3]))
    snap = parse_hourly(pstryk_payload(frames), _now())
    assert len(snap.buy) == 24


def test_string_prices_with_comma() -> None:
    today = local_midnight_utc(2026, 10, 16)
    frames = pstryk_frames(today, 24)
    for f in frames:
        f["metrics"]["pricing"]["price_gross"] = str(f["metrics"]["pricing"]["price_gross"]).replace(".", ",")
    snap = parse_hourly(pstryk_payload(frames), _now())
    assert len(snap.buy) == 24


@pytest.mark.parametrize(
    ("day", "hours"),
    [((2026, 3, 29), 23), ((2026, 10, 25), 25), ((2026, 10, 16), 24)],
)
def test_dst_day_lengths(day: tuple[int, int, int], hours: int) -> None:
    start = local_midnight_utc(*day)
    assert hours_in_local_day(start + timedelta(hours=5)) == hours
    s, e = local_day_bounds(start + timedelta(hours=5))
    assert (e - s) == timedelta(hours=hours)


@pytest.mark.parametrize(("day", "hours"), [((2026, 3, 29), 23), ((2026, 10, 25), 25)])
def test_dst_day_confirmation(day: tuple[int, int, int], hours: int) -> None:
    start = local_midnight_utc(*day)
    frames = pstryk_frames(start, hours)
    snap = parse_hourly(pstryk_payload(frames), start - timedelta(hours=8))
    assert len(snap.buy) == hours
    assert snap.tomorrow_confirmed


def test_placeholder_detection() -> None:
    assert is_placeholder_day([0.5] * 24, 24)
    assert is_placeholder_day([0.5, 0.6] * 5, 24)
    assert not is_placeholder_day([0.1 * i for i in range(24)], 24)


def test_parse_daily() -> None:
    frames = pstryk_frames(local_midnight_utc(2026, 10, 1), 3)
    daily, summary = parse_daily(pstryk_payload(frames))
    assert len(daily) == 3
    assert summary == {"meterValues": {}, "cost": {}}


def test_retry_after_parsing() -> None:
    assert parse_retry_after("120") == 120
    now = datetime(2026, 10, 16, 12, tzinfo=UTC)
    assert parse_retry_after("Fri, 16 Oct 2026 12:10:00 GMT", now) == 600
    assert parse_retry_after(None) is None
    assert parse_retry_after("garbage") is None


def test_budget_sliding_window() -> None:
    clock = [1000.0]
    budget = RequestBudget(2, 3600, clock=lambda: clock[0])
    assert budget.try_acquire()
    assert budget.try_acquire()
    assert not budget.try_acquire()
    assert budget.seconds_until_available() == pytest.approx(3600)
    clock[0] += 3601
    assert budget.try_acquire()
    budget.block_for(100)
    assert budget.remaining() == 0
    state = budget.export()
    other = RequestBudget(2, 3600, clock=lambda: clock[0])
    other.restore(state)
    assert other.remaining() == 0


def test_budget_shared_per_key() -> None:
    assert shared_budget("sk-abc") is shared_budget("sk-abc")
    assert shared_budget("sk-abc") is not shared_budget("sk-xyz")
    assert "sk-abc" not in key_fingerprint("sk-abc")


PSTRYK_URL = "https://api.pstryk.pl/integrations/meter-data/unified-metrics/"


@pytest.fixture
async def session(aioclient_mock: AiohttpClientMocker):
    sess = aioclient_mock.create_session(asyncio.get_running_loop())
    yield sess
    await sess.close()


async def test_http_auth_failure(aioclient_mock: AiohttpClientMocker, session) -> None:
    client = PstrykClient(session, "sk-secret", budget=RequestBudget(5, 3600))
    aioclient_mock.get(PSTRYK_URL, status=401)
    with pytest.raises(ProviderAuthError):
        await client.validate(_now())


async def test_http_429_blocks_budget(
    aioclient_mock: AiohttpClientMocker, session, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    budget = RequestBudget(5, 3600)
    client = PstrykClient(session, "sk-very-secret-key", budget=budget)
    aioclient_mock.get(PSTRYK_URL, status=429, headers={"Retry-After": "900"})
    with pytest.raises(ProviderRateLimited) as exc:
        await client.fetch_hourly(_now(), _now() + timedelta(hours=1), ["pricing"])
    assert exc.value.retry_after == 900
    assert budget.remaining() == 0
    calls = aioclient_mock.call_count
    # a further call must not hit the network at all
    with pytest.raises(ProviderRateLimited):
        await client.fetch_hourly(_now(), _now() + timedelta(hours=1), ["pricing"])
    assert aioclient_mock.call_count == calls
    assert "sk-very-secret-key" not in caplog.text


async def test_http_timeout(aioclient_mock: AiohttpClientMocker, session) -> None:
    client = PstrykClient(session, "sk-x", budget=RequestBudget(5, 3600))
    aioclient_mock.get(PSTRYK_URL, exc=TimeoutError())
    with pytest.raises(ProviderUnavailable):
        await client.validate(_now())


async def test_http_server_error(aioclient_mock: AiohttpClientMocker, session) -> None:
    client = PstrykClient(session, "sk-x", budget=RequestBudget(5, 3600))
    aioclient_mock.get(PSTRYK_URL, status=503)
    with pytest.raises(ProviderUnavailable):
        await client.validate(_now())


async def test_http_network_outage(aioclient_mock: AiohttpClientMocker, session) -> None:
    client = PstrykClient(session, "sk-x", budget=RequestBudget(5, 3600))
    aioclient_mock.get(PSTRYK_URL, exc=aiohttp.ClientConnectionError("down"))
    with pytest.raises(ProviderUnavailable):
        await client.validate(_now())


async def test_http_success_sends_auth_header(aioclient_mock: AiohttpClientMocker, session) -> None:
    today = local_midnight_utc(2026, 10, 16)
    client = PstrykClient(session, "sk-x", budget=RequestBudget(5, 3600))
    aioclient_mock.get(PSTRYK_URL, json=pstryk_payload(pstryk_frames(today, 24)))
    raw = await client.fetch_hourly(today, today + timedelta(days=1), ["pricing", "meter_values", "cost"])
    _method, url, _, headers = aioclient_mock.mock_calls[-1]
    assert headers["Authorization"] == "sk-x"
    assert url.query["resolution"] == "hour"
    assert "for_tz" not in url.query  # not allowed with hour resolution
    assert len(raw["frames"]) == 24
