"""Open-Meteo: four endpoints behind one cache.

The cache is what makes hosting this safe on Open-Meteo's free tier. An entry
is fresh for CACHE_TTL (15 minutes, the API's own update interval);
concurrent requests for one key share a single HTTP call; an HTTP 429 pauses
that endpoint for 60 seconds; and an expired entry up to STALE_MAX old is
served, marked stale, rather than an error.
"""

from __future__ import annotations

import asyncio
import bisect
import time
from collections import deque
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx

from .config import Settings

PAUSE_AFTER_429 = 60.0
MAX_CITY = 100  # characters; the longest place names are well under it


class UpstreamError(Exception):
    """An endpoint failed and no usable stale copy exists."""


class RateLimited(UpstreamError):
    """HTTP 429 from Open-Meteo."""


class Busy(UpstreamError):
    """Too many new lookups from everyone together; nothing was asked upstream."""


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
    def __init__(
        self,
        ttl: float,
        stale_max: float,
        max_entries: int,
        clock: Callable[[], float] = time.time,  # entry times, shown on the page
        fetches_per_minute: int = 120,
        fetches_per_hour: int = 4000,
        fetches_per_day: int = 8000,
        limit_clock: Callable[[], float] = time.monotonic,  # never steps back
    ) -> None:
        self.limit_clock = limit_clock
        self.ttl, self.stale_max, self.max_entries, self.clock = ttl, stale_max, max_entries, clock
        # Open-Meteo's free tier allows 600 a minute, 5,000 an hour, 10,000 a day per IP.
        # ponytail: per process; one client may use the whole budget (cached cities still work)
        self.fetches_per_minute, self.fetches_per_hour = fetches_per_minute, fetches_per_hour
        self.fetches_per_day = fetches_per_day
        self._entries: dict[tuple, _Entry] = {}  # order = last use, least recent first
        self._inflight: dict[tuple, asyncio.Task] = {}
        self._paused_until: dict[str, float] = {}
        self._fetches: deque[float] = deque()  # when each upstream call of the last day started

    def __len__(self) -> int:
        return len(self._entries)

    def forget(self, key: tuple) -> None:
        """Drop an answer that turned out unusable: the next request asks again."""
        self._entries.pop(key, None)

    async def get(self, key: tuple, fetch: Callable[[], Awaitable[dict[str, Any]]]) -> Result:
        """`key[0]` names the endpoint; the 429 pause applies per endpoint."""
        now = self.clock()
        entry = self._entries.get(key)
        if entry and now - entry.at < self.ttl:
            self._entries[key] = self._entries.pop(key)  # used: last to be evicted
            return Result(entry.data, entry.at, stale=False)
        if now < self._paused_until.get(key[0], 0.0):
            return self._stale_or_raise(entry, now, RateLimited(f"{key[0]}: paused after HTTP 429"))
        task = self._inflight.get(key)
        if task is None:
            # Everyone together: a script cycling through city names must not spend the free
            # quota (then a 429 for every visitor). Over the limit, a stale copy still serves.
            tick = self.limit_clock()
            while self._fetches and self._fetches[0] <= tick - 86400:
                self._fetches.popleft()
            limits = (
                (60, self.fetches_per_minute),
                (3600, self.fetches_per_hour),
                (86400, self.fetches_per_day),
            )
            if any(
                len(self._fetches) - bisect.bisect_right(self._fetches, tick - s) >= n
                for s, n in limits
            ):
                return self._stale_or_raise(entry, now, Busy("busy: too many new lookups"))
            self._fetches.append(tick)
            task = asyncio.create_task(self._refresh(key, fetch))
            self._inflight[key] = task
            task.add_done_callback(lambda _done: self._inflight.pop(key, None))
        # shield: a visitor who leaves cancels only their own wait, never the
        # shared fetch the other visitors are waiting on.
        return await asyncio.shield(task)

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


FORECAST = "https://api.open-meteo.com/v1/forecast"
ENSEMBLE = "https://ensemble-api.open-meteo.com/v1/ensemble"
AIR = "https://air-quality-api.open-meteo.com/v1/air-quality"
GEOCODE = "https://geocoding-api.open-meteo.com/v1/search"
TIMEOUT = 10.0

UNIT_PARAMS: dict[str, dict[str, str]] = {
    "metric": {},
    "imperial": {
        "temperature_unit": "fahrenheit",
        "wind_speed_unit": "mph",
        "precipitation_unit": "inch",
    },
}


@dataclass(frozen=True)
class Place:
    name: str
    admin1: str
    country_code: str
    latitude: float
    longitude: float

    @property
    def label(self) -> str:
        return ", ".join(p for p in (self.name, self.admin1, self.country_code) if p)


def forecast_params(place: Place, units: str) -> dict[str, Any]:
    return {
        "latitude": place.latitude,
        "longitude": place.longitude,
        "timezone": "auto",
        "forecast_days": 7,
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,"
        "wind_speed_10m,precipitation,weather_code",
        "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code",
        **UNIT_PARAMS[units],
    }


def ensemble_params(place: Place, units: str) -> dict[str, Any]:
    temp = {k: v for k, v in UNIT_PARAMS[units].items() if k == "temperature_unit"}
    return {
        "latitude": place.latitude,
        "longitude": place.longitude,
        "timezone": "auto",
        "forecast_days": 7,
        "hourly": "temperature_2m",
        "models": "ecmwf_ifs025",
        **temp,
    }


def air_params(place: Place) -> dict[str, Any]:
    return {
        "latitude": place.latitude,
        "longitude": place.longitude,
        "timezone": "auto",
        "forecast_days": 5,
        "current": "european_aqi,pm2_5,birch_pollen,grass_pollen,ragweed_pollen",
        "hourly": "european_aqi",
    }


def geocode_params(text: str, count: int = 5) -> dict[str, Any]:
    return {"name": text, "count": count, "language": "en", "format": "json"}


async def _get_json(http: httpx.AsyncClient, url: str, params: dict[str, Any]) -> dict[str, Any]:
    try:
        r = await http.get(url, params=params, timeout=TIMEOUT)
    except httpx.HTTPError as e:  # timeouts, refused connections, DNS
        raise UpstreamError(f"{url}: {e.__class__.__name__}") from None
    if r.status_code == 429:
        raise RateLimited(f"{url}: HTTP 429")
    if r.status_code >= 400:
        raise UpstreamError(f"{url}: HTTP {r.status_code}")
    try:
        return r.json()
    except ValueError:
        raise UpstreamError(f"{url}: response is not JSON") from None


class OpenMeteo:
    def __init__(
        self,
        settings: Settings,
        http: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.http = http or httpx.AsyncClient()
        self.cache = Cache(settings.cache_ttl, settings.stale_max, settings.cache_max, clock)

    async def aclose(self) -> None:
        await self.http.aclose()

    @staticmethod
    def _at(place: Place) -> tuple[float, float]:
        return round(place.latitude, 3), round(place.longitude, 3)

    async def forecast(self, place: Place, units: str) -> Result:
        params = forecast_params(place, units)
        return await self.cache.get(
            ("forecast", *self._at(place), units), lambda: _get_json(self.http, FORECAST, params)
        )

    async def ensemble(self, place: Place, units: str) -> Result:
        params = ensemble_params(place, units)
        return await self.cache.get(
            ("ensemble", *self._at(place), units), lambda: _get_json(self.http, ENSEMBLE, params)
        )

    async def air(self, place: Place) -> Result:
        params = air_params(place)
        return await self.cache.get(
            ("air", *self._at(place)), lambda: _get_json(self.http, AIR, params)
        )

    async def search(self, text: str, count: int = 5) -> list[Place]:
        name = text.strip()[:MAX_CITY]  # a cache key and an upstream parameter
        if not name:
            return []
        key = ("geocode", name.lower(), count)
        result = await self.cache.get(
            key, lambda: _get_json(self.http, GEOCODE, geocode_params(name, count))
        )
        try:
            return [
                Place(
                    _text(r["name"]),
                    str(r.get("admin1") or ""),
                    str(r.get("country_code") or ""),
                    float(r["latitude"]),
                    float(r["longitude"]),
                )
                for r in result.data.get("results", [])
            ]
        except (KeyError, TypeError, AttributeError, ValueError) as e:  # the page shows its message
            self.cache.forget(key)
            raise UpstreamError("geocoding: unexpected answer") from e


def _text(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError(f"expected a name, got {value!r}")
    return value


def match_place(places: list[Place], text: str) -> Place | None:
    """'Springfield, Missouri, US' picks that Springfield; a bare name takes the
    first result. Everything after the first comma must match a place's region
    or country code."""
    wanted = [p.strip().lower() for p in text.split(",")[1:] if p.strip()]
    for place in places:
        tags = {place.admin1.lower(), place.country_code.lower()}
        if all(w in tags for w in wanted):
            return place
    return None


def city_from_timezone(tz: str) -> str | None:
    """'America/New_York' -> 'New York'. None for zones that name no city."""
    if "/" not in tz or tz.startswith("Etc/"):
        return None
    return tz.rsplit("/", 1)[1].replace("_", " ")


SEARCH_GAP = 0.3  # seconds; the browser throttles at 0.4, this holds if a client does not
SEARCHES_PER_MINUTE = 30  # one client's share of the shared lookup budget (120 a minute)


def allow_search(seen: dict, now: float) -> bool:
    """Server-side search throttle for one client (`seen` lives with the client)."""
    if now - seen.get("last", float("-inf")) < SEARCH_GAP:
        return False
    recent = seen.setdefault("recent", deque())
    while recent and recent[0] <= now - 60:
        recent.popleft()
    seen["capped"] = len(recent) >= SEARCHES_PER_MINUTE  # the page says why
    if seen["capped"]:
        return False
    seen["last"] = now
    recent.append(now)
    return True
