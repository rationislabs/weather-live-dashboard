"""The cache is what keeps a hosted copy inside Open-Meteo's free tier."""

import asyncio

import pytest

from weather_live import openmeteo as om


def clock_at(start: float = 1000.0):
    now = [start]
    return now, (lambda: now[0])


def counting(value=None, error: Exception | None = None):
    calls = {"n": 0}

    async def fetch():
        calls["n"] += 1
        if error is not None:
            raise error
        return value if value is not None else {"n": calls["n"]}

    return calls, fetch


async def test_fresh_hit_does_not_refetch():
    now, clock = clock_at()
    cache = om.Cache(900, 21600, 10, clock)
    calls, fetch = counting()
    await cache.get(("forecast", 1), fetch)
    now[0] += 899
    r = await cache.get(("forecast", 1), fetch)
    assert calls["n"] == 1 and r.stale is False


async def test_expired_entry_is_refetched():
    now, clock = clock_at()
    cache = om.Cache(900, 21600, 10, clock)
    calls, fetch = counting()
    await cache.get(("forecast", 1), fetch)
    now[0] += 900
    r = await cache.get(("forecast", 1), fetch)
    assert calls["n"] == 2 and r.data == {"n": 2}


async def test_concurrent_requests_share_one_call():
    _, clock = clock_at()
    cache = om.Cache(900, 21600, 10, clock)
    gate, calls = asyncio.Event(), {"n": 0}

    async def slow():
        calls["n"] += 1
        await gate.wait()
        return {"v": 1}

    t1 = asyncio.create_task(cache.get(("forecast", 1), slow))
    t2 = asyncio.create_task(cache.get(("forecast", 1), slow))
    await asyncio.sleep(0.01)
    gate.set()
    r1, r2 = await asyncio.gather(t1, t2)
    assert calls["n"] == 1 and r1.data == r2.data == {"v": 1}


async def test_failure_serves_stale_until_stale_max():
    now, clock = clock_at()
    cache = om.Cache(900, 21600, 10, clock)
    _, ok = counting({"v": "old"})
    await cache.get(("air", 1), ok)
    _, broken = counting(error=om.UpstreamError("HTTP 500"))
    now[0] += 3600
    r = await cache.get(("air", 1), broken)
    assert r.stale is True and r.data == {"v": "old"} and r.fetched_at == 1000.0
    now[0] = 1000.0 + 21601
    with pytest.raises(om.UpstreamError):
        await cache.get(("air", 1), broken)


async def test_429_pauses_the_endpoint_for_60_seconds():
    now, clock = clock_at()
    cache = om.Cache(900, 21600, 10, clock)
    _, ok = counting({"v": "old"})
    await cache.get(("ensemble", 1), ok)
    now[0] += 1000
    calls, limited = counting(error=om.RateLimited("HTTP 429"))
    assert (await cache.get(("ensemble", 1), limited)).stale is True
    now[0] += 30
    assert (await cache.get(("ensemble", 1), limited)).stale is True
    assert calls["n"] == 1, "called the API again inside the pause"
    other_calls, other = counting()
    await cache.get(("forecast", 1), other)
    assert other_calls["n"] == 1, "a 429 on one endpoint paused another"
    now[0] += 31
    await cache.get(("ensemble", 1), limited)
    assert calls["n"] == 2


async def test_no_stale_copy_means_the_error_propagates():
    _, clock = clock_at()
    cache = om.Cache(900, 21600, 10, clock)
    _, broken = counting(error=om.UpstreamError("timeout"))
    with pytest.raises(om.UpstreamError):
        await cache.get(("forecast", 9), broken)


async def test_size_cap_evicts_the_oldest():
    _, clock = clock_at()
    cache = om.Cache(900, 21600, 2, clock)
    for k in (1, 2, 3):
        _, fetch = counting()
        await cache.get(("forecast", k), fetch)
    assert len(cache) == 2
    calls, fetch = counting()
    await cache.get(("forecast", 1), fetch)
    assert calls["n"] == 1, "key 1 should have been evicted"


async def test_a_cancelled_waiter_does_not_break_the_others():
    """A visitor who leaves mid-request must not cancel the shared fetch."""
    _, clock = clock_at()
    cache = om.Cache(900, 21600, 10, clock)
    gate = asyncio.Event()

    async def slow():
        await gate.wait()
        return {"v": 1}

    leaver = asyncio.create_task(cache.get(("forecast", 1), slow))
    stayer = asyncio.create_task(cache.get(("forecast", 1), slow))
    await asyncio.sleep(0.01)
    leaver.cancel()
    await asyncio.sleep(0.01)
    gate.set()
    assert (await stayer).data == {"v": 1}
    assert len(cache) == 1, "the result was not cached"
