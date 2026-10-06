"""Settings, from the environment only, so a host can configure the container
without a code change."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    default_city: str
    cache_ttl: int  # seconds an API response is fresh; Open-Meteo updates every 15 minutes
    cache_max: int  # cached responses kept, oldest evicted first
    stale_max: int  # seconds an expired response may still be shown when the API fails


def load() -> Settings:
    env = os.environ.get
    return Settings(
        host=env("HOST", "127.0.0.1"),
        port=int(env("PORT", "8080")),
        default_city=env("DEFAULT_CITY", "Vienna"),
        cache_ttl=int(env("CACHE_TTL", "900")),
        cache_max=int(env("CACHE_MAX", "500")),
        stale_max=int(env("STALE_MAX", "21600")),
    )
