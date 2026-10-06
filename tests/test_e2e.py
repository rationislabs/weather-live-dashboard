"""One real run against Open-Meteo. `uv run inv e2e`; never in CI."""

import httpx
import pytest

from weather_live import config
from weather_live import openmeteo as om

pytestmark = pytest.mark.e2e


async def test_real_api_shapes():
    api = om.OpenMeteo(config.load(), http=httpx.AsyncClient())
    try:
        place = (await api.search("Vienna"))[0]
        f = (await api.forecast(place, "metric")).data
        assert len(f["daily"]["time"]) == 7 and "temperature_2m" in f["current"]
        e = (await api.ensemble(place, "metric")).data["hourly"]
        assert sum(k.startswith("temperature_2m") for k in e) >= 30
        a = (await api.air(place)).data
        assert "european_aqi" in a["current"]
    finally:
        await api.aclose()
