import httpx
import pytest

from weather_live import config
from weather_live import openmeteo as om

GRAZ = om.Place("Graz", "Styria", "AT", 47.067, 15.45)


def client() -> om.OpenMeteo:
    return om.OpenMeteo(config.load(), http=httpx.AsyncClient())


async def test_search_returns_places(api_routes):
    api = client()
    places = await api.search("Graz")
    assert places[0].name == "Graz" and places[0].country_code == "AT"
    assert await api.search("Nowhereville") == []
    assert await api.search("   ") == []
    await api.aclose()


async def test_units_reach_the_request(api_routes):
    api = client()
    await api.forecast(GRAZ, "imperial")
    sent = api_routes["forecast"].calls.last.request.url.params
    assert sent["temperature_unit"] == "fahrenheit" and sent["wind_speed_unit"] == "mph"
    await api.ensemble(GRAZ, "imperial")
    sent = api_routes["ensemble"].calls.last.request.url.params
    assert sent["temperature_unit"] == "fahrenheit" and "wind_speed_unit" not in sent
    await api.aclose()


async def test_metric_and_imperial_are_cached_separately(api_routes):
    api = client()
    await api.forecast(GRAZ, "metric")
    await api.forecast(GRAZ, "imperial")
    await api.forecast(GRAZ, "metric")
    assert api_routes["forecast"].call_count == 2
    await api.aclose()


async def test_timeout_becomes_upstream_error(api_routes):
    api_routes["air"].mock(side_effect=httpx.ReadTimeout("slow"))
    api = client()
    with pytest.raises(om.UpstreamError):
        await api.air(GRAZ)
    await api.aclose()


async def test_429_is_rate_limited(api_routes):
    api_routes["ensemble"].mock(return_value=httpx.Response(429))
    api = client()
    with pytest.raises(om.RateLimited):
        await api.ensemble(GRAZ, "metric")
    await api.aclose()


def test_match_place_uses_region_and_country():
    places = [
        om.Place("Springfield", "Illinois", "US", 39.8, -89.6),
        om.Place("Springfield", "Missouri", "US", 37.2, -93.3),
        om.Place("São Paulo", "São Paulo", "BR", -23.5, -46.6),
    ]
    assert om.match_place(places, "Springfield, Missouri, US").admin1 == "Missouri"
    assert om.match_place(places, "Springfield").admin1 == "Illinois"
    assert om.match_place(places, "Springfield, Ohio") is None
    assert om.match_place(places[2:], "São Paulo, BR").country_code == "BR"
    assert om.Place("Graz", "", "AT", 0, 0).label == "Graz, AT"


def test_city_from_timezone():
    assert om.city_from_timezone("America/New_York") == "New York"
    assert om.city_from_timezone("America/Indiana/Indianapolis") == "Indianapolis"
    assert om.city_from_timezone("Europe/Vienna") == "Vienna"
    for none in ("UTC", "Etc/GMT+2", ""):
        assert om.city_from_timezone(none) is None
