"""Developer tasks. List them with `uv run inv --list`."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
from invoke import task

ROOT = Path(__file__).parent
FIXTURES = ROOT / "tests" / "fixtures"


@task
def fixtures(c):
    """Record real Open-Meteo responses for the offline tests (Vienna, Graz)."""
    from weather_live import openmeteo as om

    FIXTURES.mkdir(parents=True, exist_ok=True)

    def save(name: str, url: str, params: dict) -> dict:
        data = httpx.get(url, params=params, timeout=30).raise_for_status().json()
        (FIXTURES / f"{name}.json").write_text(json.dumps(data, indent=1) + "\n")
        print(f"wrote tests/fixtures/{name}.json")
        return data

    for city in ("Vienna", "Graz"):
        save(f"geocode_{city.lower()}", om.GEOCODE, om.geocode_params(city))
    first = json.loads((FIXTURES / "geocode_vienna.json").read_text())["results"][0]
    vienna = om.Place(first["name"], first.get("admin1", ""), first.get("country_code", ""),
                      first["latitude"], first["longitude"])
    save("forecast_vienna", om.FORECAST, om.forecast_params(vienna, "metric"))
    save("ensemble_vienna", om.ENSEMBLE, om.ensemble_params(vienna, "metric"))
    save("air_vienna", om.AIR, om.air_params(vienna))
