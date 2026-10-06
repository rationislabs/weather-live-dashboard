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
    vienna = om.Place(
        first["name"],
        first.get("admin1", ""),
        first.get("country_code", ""),
        first["latitude"],
        first["longitude"],
    )
    save("forecast_vienna", om.FORECAST, om.forecast_params(vienna, "metric"))
    save("ensemble_vienna", om.ENSEMBLE, om.ensemble_params(vienna, "metric"))
    save("air_vienna", om.AIR, om.air_params(vienna))


@task
def dev(c):
    """Run the app on http://127.0.0.1:8080 (loopback only)."""
    c.run("uv run python main.py", pty=True)


@task
def up(c):
    """Build and start the container on http://127.0.0.1:8080."""
    c.run("docker compose up -d --build --wait")
    print("http://127.0.0.1:8080")


@task
def down(c):
    c.run("docker compose down")


@task
def test(c):
    c.run("uv run pytest", pty=True)


@task
def lint(c):
    c.run("uv run ruff check . && uv run ruff format --check .")


@task
def e2e(c):
    """One run against the real Open-Meteo API."""
    c.run("uv run pytest -m e2e", pty=True)
