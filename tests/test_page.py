import httpx
from nicegui.testing import User


async def test_renders_every_panel(user: User, api_routes) -> None:
    await user.open("/?city=Vienna")
    for text in ("Vienna", "Next 7 days", "How sure is the forecast?", "Air quality",
                 "Weather data by Open-Meteo.com"):
        await user.should_see(text)


async def test_one_failing_endpoint_leaves_the_rest(user: User, api_routes) -> None:
    api_routes["air"].mock(return_value=httpx.Response(500))
    await user.open("/?city=Vienna")
    await user.should_see("Couldn't load air quality.")
    await user.should_see("Retry")
    await user.should_see("How sure is the forecast?")


async def test_retry_reloads_the_panel(user: User, api_routes, fx) -> None:
    # two failures: the page warms the cache, then the panel asks again
    api_routes["air"].mock(side_effect=[httpx.Response(500), httpx.Response(500),
                                        httpx.Response(200, json=fx("air_vienna"))])
    await user.open("/?city=Vienna")
    await user.should_see("Couldn't load air quality.")
    user.find("Retry").click()
    await user.should_see("European AQI")


async def test_unknown_city_falls_back_with_a_notice(user: User, api_routes) -> None:
    await user.open("/?city=Nowhereville")
    await user.should_see("No place called 'Nowhereville'. Showing Vienna.")


async def test_imperial_units(user: User, api_routes) -> None:
    await user.open("/?city=Vienna&units=imperial")
    await user.should_see("°F")


async def test_geocoding_down_shows_retry(user: User, api_routes) -> None:
    api_routes["geocode"].mock(return_value=httpx.Response(503))
    await user.open("/?city=Vienna")
    await user.should_see("Couldn't reach the weather service.")


async def test_stale_panel_says_so(user: User, api_routes) -> None:
    from weather_live import page
    await user.open("/?city=Vienna")
    await user.should_see("Air quality")
    for entry in page.api.cache._entries.values():  # age every cached response
        entry.at -= 3600
    api_routes["air"].mock(return_value=httpx.Response(500))
    await user.open("/?city=Vienna")
    await user.should_see("(couldn't refresh)")


async def test_null_pollen_hides_tiles(user: User, api_routes, fx) -> None:
    air = fx("air_vienna")
    for k in ("birch_pollen", "grass_pollen", "ragweed_pollen"):
        air["current"][k] = None
    api_routes["air"].mock(return_value=httpx.Response(200, json=air))
    await user.open("/?city=Vienna")
    await user.should_see("European AQI")
    await user.should_not_see("pollen")
