"""Shared test setup. NiceGUI's `user` fixture runs main.py in-process."""

pytest_plugins = ["nicegui.testing.user_plugin"]

import json
from pathlib import Path

import httpx
import pytest
import respx

from weather_live import openmeteo as om

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def fx():
    """Load a recorded response: fx("forecast_vienna")."""
    return lambda name: json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.fixture
def api_routes(fx):
    """Every endpoint answered from recordings; geocoding by the `name` param
    (unknown names get no results). Tests make one endpoint fail with
    api_routes["air"].mock(return_value=httpx.Response(500))."""

    def geocode(request: httpx.Request) -> httpx.Response:
        path = FIXTURES / f"geocode_{request.url.params['name'].lower()}.json"
        return httpx.Response(200, json=json.loads(path.read_text()) if path.exists() else {})

    with respx.mock(assert_all_called=False) as router:
        router.get(om.GEOCODE, name="geocode").mock(side_effect=geocode)
        router.get(om.FORECAST, name="forecast").mock(
            return_value=httpx.Response(200, json=fx("forecast_vienna"))
        )
        router.get(om.ENSEMBLE, name="ensemble").mock(
            return_value=httpx.Response(200, json=fx("ensemble_vienna"))
        )
        router.get(om.AIR, name="air").mock(return_value=httpx.Response(200, json=fx("air_vienna")))
        yield router
