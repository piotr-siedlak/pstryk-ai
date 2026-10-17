"""Shared HTTP helpers: errors, backoff, Retry-After handling and request budgets."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
import logging
import random
import time
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

USER_AGENT = "PstrykAI-HomeAssistant/0.1 (+https://github.com/piotr-siedlak/pstryk-ai)"


class ProviderError(Exception):
    """Base error for data providers."""


class ProviderAuthError(ProviderError):
    """Authentication rejected (HTTP 401/403)."""


class ProviderRateLimited(ProviderError):
    """Provider returned HTTP 429 or the local budget is exhausted."""

    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class ProviderUnavailable(ProviderError):
    """Network error, timeout or HTTP 5xx."""


class ProviderDataError(ProviderError):
    """Unexpected or malformed payload."""


class ProviderNotFound(ProviderDataError):
    """HTTP 404 – for Pstryk: meter missing, not authorised or no active contract."""


def parse_retry_after(value: str | None, now: datetime | None = None) -> float | None:
    """Parse a Retry-After header (seconds or HTTP date) into seconds."""
    if not value:
        return None
    value = value.strip()
    try:
        return max(0.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    now = now or datetime.now(UTC)
    return max(0.0, (when - now).total_seconds())


def backoff_delay(attempt: int, base: float = 2.0, cap: float = 300.0) -> float:
    """Exponential backoff with full jitter."""
    return random.uniform(0, min(cap, base * (2**attempt)))


@dataclass
class RequestBudget:
    """Sliding-window request budget shared by everyone using the same key.

    ``blocked_until`` is set after HTTP 429 so that *no* request is attempted
    before the provider-specified time.
    """

    limit: int
    window_s: float
    clock: Callable[[], float] = time.time
    _calls: deque[float] = field(default_factory=deque)
    blocked_until: float = 0.0

    def _prune(self) -> None:
        now = self.clock()
        while self._calls and now - self._calls[0] >= self.window_s:
            self._calls.popleft()

    def remaining(self) -> int:
        self._prune()
        if self.clock() < self.blocked_until:
            return 0
        return max(0, self.limit - len(self._calls))

    def seconds_until_available(self) -> float:
        self._prune()
        now = self.clock()
        wait = max(0.0, self.blocked_until - now)
        if len(self._calls) >= self.limit:
            wait = max(wait, self._calls[0] + self.window_s - now)
        return wait

    def try_acquire(self) -> bool:
        if self.remaining() <= 0:
            return False
        self._calls.append(self.clock())
        return True

    def block_for(self, seconds: float) -> None:
        self.blocked_until = max(self.blocked_until, self.clock() + seconds)

    def export(self) -> dict[str, Any]:
        self._prune()
        return {"calls": list(self._calls), "blocked_until": self.blocked_until}

    def restore(self, data: dict[str, Any]) -> None:
        self._calls = deque(sorted(float(c) for c in data.get("calls", [])))
        self.blocked_until = float(data.get("blocked_until", 0.0))
        self._prune()


async def request_json(
    session: aiohttp.ClientSession,
    method: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
    retries: int = 2,
    expect: str = "json",
    provider: str = "provider",
) -> Any:
    """Perform a request with retries for transient errors.

    429 is never retried here: the caller must respect ``retry_after``.
    """
    merged_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        merged_headers.update(headers)
    last_error: Exception | None = None
    for attempt in range(retries + 1):
        try:
            async with session.request(
                method,
                url,
                params=params,
                headers=merged_headers,
                timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                if resp.status in (401, 403):
                    raise ProviderAuthError(f"{provider}: authentication failed ({resp.status})")
                if resp.status == 429:
                    raise ProviderRateLimited(
                        f"{provider}: rate limited",
                        parse_retry_after(resp.headers.get("Retry-After")),
                    )
                if resp.status >= 500:
                    raise ProviderUnavailable(f"{provider}: HTTP {resp.status}")
                if resp.status == 404:
                    raise ProviderNotFound(f"{provider}: HTTP 404 (not found / no active contract)")
                if resp.status >= 400:
                    body = (await resp.text())[:300]
                    raise ProviderDataError(f"{provider}: HTTP {resp.status}: {body}")
                if expect == "text":
                    return await resp.text()
                try:
                    return await resp.json(content_type=None)
                except (ValueError, aiohttp.ContentTypeError) as err:
                    raise ProviderDataError(f"{provider}: invalid JSON") from err
        except (ProviderAuthError, ProviderRateLimited, ProviderDataError):
            raise
        except (TimeoutError, aiohttp.ClientError, ProviderUnavailable) as err:
            last_error = err
            if attempt >= retries:
                break
            delay = backoff_delay(attempt, base=1.0, cap=10.0)
            _LOGGER.debug("%s: transient error %s, retry in %.1fs", provider, err, delay)
            await asyncio.sleep(delay)
    raise ProviderUnavailable(f"{provider}: {last_error}") from last_error


def utc_now() -> datetime:
    return datetime.now(UTC)


def daterange(start: datetime, end: datetime, step: timedelta) -> list[datetime]:
    out: list[datetime] = []
    cur = start
    while cur < end:
        out.append(cur)
        cur += step
    return out
