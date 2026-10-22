import httpx
from nicegui.testing import User


async def test_renders_every_panel(user: User, api_routes) -> None:
    await user.open("/?city=Vienna")
    for text in (
        "Vienna",
        "Next 7 days",
        "How sure is the forecast?",
        "Air quality",
        "Weather data by Open-Meteo.com",
    ):
        await user.should_see(text)


async def test_one_failing_endpoint_leaves_the_rest(user: User, api_routes) -> None:
    api_routes["air"].mock(return_value=httpx.Response(500))
    await user.open("/?city=Vienna")
    await user.should_see("Couldn't load air quality.")
    await user.should_see("Retry")
    await user.should_see("How sure is the forecast?")


async def test_retry_reloads_the_panel(user: User, api_routes, fx) -> None:
    # two failures: the page warms the cache, then the panel asks again
    api_routes["air"].mock(
        side_effect=[
            httpx.Response(500),
            httpx.Response(500),
            httpx.Response(200, json=fx("air_vienna")),
        ]
    )
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


async def test_a_slow_endpoint_does_not_blank_the_page(user: User, api_routes, fx) -> None:
    """NiceGUI fails a page that takes more than 3 s to build; the panels must
    fill in after the page is sent, so one slow API never blanks it."""
    import asyncio

    async def slow(request):
        await asyncio.sleep(3.5)
        return httpx.Response(200, json=fx("air_vienna"))

    api_routes["air"].mock(side_effect=slow)
    await user.open("/?city=Vienna")
    await user.should_see("How sure is the forecast?")


async def test_a_broken_answer_fails_only_its_panel(user: User, api_routes, fx) -> None:
    forecast = fx("forecast_vienna")
    forecast["current"]["temperature_2m"] = None
    api_routes["forecast"].mock(return_value=httpx.Response(200, json=forecast))
    air = fx("air_vienna")
    del air["hourly"]
    api_routes["air"].mock(return_value=httpx.Response(200, json=air))
    await user.open("/?city=Vienna")
    await user.should_see("Couldn't load current conditions.")
    await user.should_see("Couldn't load air quality.")
    await user.should_see("How sure is the forecast?")


async def test_a_huge_city_parameter_is_cut_short(user: User, api_routes) -> None:
    # The name is a cache key, an upstream parameter and part of the notice text.
    await user.open("/?city=" + "x" * 500)
    await user.should_see("Showing Vienna")
    names = [c.request.url.params["name"] for c in api_routes["geocode"].calls]
    assert names and max(len(n) for n in names) <= 100


async def test_a_busy_lookup_is_not_reported_as_an_unknown_place(user: User, api_routes) -> None:
    from weather_live import page

    await user.open("/?city=Vienna")  # the default city is cached now
    await user.should_see("Next 7 days")
    page.api.cache.fetches_per_minute = 0
    await user.open("/?city=Graz")
    await user.should_see("Too many lookups right now")
    await user.should_not_see("No place called")


async def test_a_null_region_does_not_blank_the_page(user: User, api_routes, fx) -> None:
    body = fx("geocode_vienna")
    body["results"][0]["admin1"] = None
    api_routes["geocode"].mock(return_value=httpx.Response(200, json=body))
    await user.open("/?city=Vienna")
    await user.should_see("Next 7 days")


async def test_a_late_answer_for_an_older_search_is_dropped(
    user: User, api_routes, fx, monkeypatch
) -> None:
    import asyncio

    from nicegui import ui

    from weather_live import openmeteo as om

    monkeypatch.setattr(om, "SEARCH_GAP", 0)
    gate, started = asyncio.Event(), asyncio.Event()
    older = {
        "results": [{"name": "Viechtach", "country_code": "DE", "latitude": 49, "longitude": 13}]
    }

    async def geocode(request):
        name = request.url.params["name"]
        if name == "Vie":
            started.set()
            await gate.wait()
            return httpx.Response(200, json=older)
        return httpx.Response(200, json=fx(f"geocode_{name.lower()}"))

    await user.open("/?city=Graz")
    await user.should_see("Next 7 days")
    api_routes["geocode"].mock(side_effect=geocode)
    box = user.find(ui.input)
    box.type("Vie").trigger("update:modelValue")
    await asyncio.wait_for(started.wait(), 2)  # the older search is waiting on Open-Meteo
    box.clear().type("Vienna").trigger("update:modelValue")
    await user.should_see("Vienna, Virginia, US")
    gate.set()
    await asyncio.sleep(0.1)
    await user.should_not_see("Viechtach")


async def test_a_failed_search_clears_the_old_suggestions(
    user: User, api_routes, monkeypatch
) -> None:
    from nicegui import ui

    from weather_live import openmeteo as om

    monkeypatch.setattr(om, "SEARCH_GAP", 0)
    await user.open("/?city=Vienna")
    await user.should_see("Next 7 days")
    box = user.find(ui.input)
    box.type("Graz").trigger("update:modelValue")
    await user.should_see("Graz, Styria, AT")
    api_routes["geocode"].mock(return_value=httpx.Response(503))
    box.clear().type("Zzyzx").trigger("update:modelValue")
    await user.should_not_see("Graz, Styria, AT")


async def test_a_refused_search_says_why(user: User, api_routes, monkeypatch) -> None:
    from nicegui import ui

    from weather_live import openmeteo as om
    from weather_live import page

    monkeypatch.setattr(om, "SEARCH_GAP", 0)
    monkeypatch.setattr(om, "SEARCHES_PER_MINUTE", 1)
    await user.open("/?city=Vienna")
    await user.should_see("Next 7 days")
    box = user.find(ui.input)
    box.type("Graz").trigger("update:modelValue")
    await user.should_see("Graz, Styria, AT")
    box.clear().type("Linz").trigger("update:modelValue")  # this client's minute is used up
    await user.should_see("Too many searches")
    await user.should_not_see("Graz, Styria, AT")
    monkeypatch.setattr(om, "SEARCHES_PER_MINUTE", 100)
    page.api.cache.fetches_per_minute = 0  # everyone's budget is used up
    box.clear().type("Salzburg").trigger("update:modelValue")
    await user.should_see("Too many lookups right now")
