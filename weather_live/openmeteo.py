"""Open-Meteo: four endpoints behind one cache.

The cache is what makes hosting this safe on Open-Meteo's free tier. An entry
is fresh for CACHE_TTL (15 minutes, the API's own update interval);
concurrent requests for one key share a single HTTP call; an HTTP 429 pauses
that endpoint for 60 seconds; and an expired entry up to STALE_MAX old is
served, marked stale, rather than an error.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

PAUSE_AFTER_429 = 60.0


class UpstreamError(Exception):
    """An endpoint failed and no usable stale copy exists."""


class RateLimited(UpstreamError):
    """HTTP 429 from Open-Meteo."""


@dataclass(frozen=True)
class Result:
    data: dict[str, Any]
    fetched_at: float  # epoch seconds
    stale: bool


@dataclass
class _Entry:
    data: dict[str, Any]
    at: float


class Cache:
    def __init__(self, ttl: float, stale_max: float, max_entries: int,
                 clock: Callable[[], float] = time.time) -> None:
        self.ttl, self.stale_max, self.max_entries, self.clock = ttl, stale_max, max_entries, clock
        self._entries: dict[tuple, _Entry] = {}  # insertion order = age order
        self._inflight: dict[tuple, asyncio.Task] = {}
        self._paused_until: dict[str, float] = {}

    def __len__(self) -> int:
        return len(self._entries)

    async def get(self, key: tuple, fetch: Callable[[], Awaitable[dict[str, Any]]]) -> Result:
        """`key[0]` names the endpoint; the 429 pause applies per endpoint."""
        now = self.clock()
        entry = self._entries.get(key)
        if entry and now - entry.at < self.ttl:
            return Result(entry.data, entry.at, stale=False)
        if now < self._paused_until.get(key[0], 0.0):
            return self._stale_or_raise(entry, now, RateLimited(f"{key[0]}: paused after HTTP 429"))
        task = self._inflight.get(key)
        if task is None:
            task = asyncio.create_task(self._refresh(key, fetch))
            self._inflight[key] = task
            task.add_done_callback(lambda _done: self._inflight.pop(key, None))
        return await task

    async def _refresh(self, key: tuple, fetch) -> Result:
        try:
            data = await fetch()
        except RateLimited as e:
            self._paused_until[key[0]] = self.clock() + PAUSE_AFTER_429
            return self._stale_or_raise(self._entries.get(key), self.clock(), e)
        except UpstreamError as e:
            return self._stale_or_raise(self._entries.get(key), self.clock(), e)
        now = self.clock()
        self._entries.pop(key, None)  # re-insert so the newest is last
        self._entries[key] = _Entry(data, now)
        while len(self._entries) > self.max_entries:
            del self._entries[next(iter(self._entries))]
        return Result(data, now, stale=False)

    def _stale_or_raise(self, entry: _Entry | None, now: float, error: UpstreamError) -> Result:
        if entry and now - entry.at <= self.stale_max:
            return Result(entry.data, entry.at, stale=True)
        raise error
