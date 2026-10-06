"""The one page. Layout and URL state only: data comes from openmeteo.py and
chart options from charts.py. The URL is the whole state, so a link opens
exactly the same view: /?city=Graz&units=imperial&theme=dark
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode

from nicegui import app, ui

from . import charts, config
from . import openmeteo as om

api: om.OpenMeteo | None = None


@app.on_startup
def _start() -> None:
    global api
    api = om.OpenMeteo(config.load())


@app.on_shutdown
async def _stop() -> None:
    if api is not None:
        await api.aclose()


def url(city: str, units: str, theme: str) -> str:
    return "/?" + urlencode({"city": city, "units": units, "theme": theme})


async def _find(text: str) -> om.Place | None:
    try:
        return om.match_place(await api.search(text.split(",")[0]), text)
    except om.UpstreamError:
        return None


async def resolve(text: str, default: str) -> tuple[om.Place | None, str]:
    """The place for `text`, else the default, plus a notice if it fell back."""
    if text and (place := await _find(text)):
        return place, ""
    notice = f"No place called '{text}'. Showing {default}." if text else ""
    return await _find(default), notice


def stamp(result: om.Result, offset_seconds: int) -> str:
    """Fetch time in the city's own time zone."""
    at = datetime.fromtimestamp(result.fetched_at, timezone(timedelta(seconds=offset_seconds)))
    return f"From {at:%H:%M} (couldn't refresh)" if result.stale else f"Updated {at:%H:%M}"


def panel(what: str, load: Callable[[], Awaitable[om.Result]],
          render: Callable[[om.Result], None]):
    """A section that fails on its own: an error and Retry, never a blank page."""

    @ui.refreshable
    async def body() -> None:
        try:
            result = await load()
        except om.UpstreamError:
            with ui.row().classes("items-center"):
                ui.label(f"Couldn't load {what}.")
                ui.button("Retry", on_click=body.refresh).props("flat")
            return
        render(result)
        if result.stale:  # served from the cache after a failed refresh
            ui.label(stamp(result, result.data.get("utc_offset_seconds", 0))).classes(
                "text-sm opacity-70")

    return body


def chart_or_table(options: list[dict], columns: list[dict], rows: list[dict]) -> None:
    table_on = ui.switch("Show as table")
    with ui.column().classes("w-full").bind_visibility_from(table_on, "value",
                                                             backward=lambda v: not v):
        for option in options:
            ui.echart(option).classes("w-full h-64")
    ui.table(columns=columns, rows=rows, row_key=columns[0]["field"]).classes(
        "w-full").bind_visibility_from(table_on, "value")


def header(place: om.Place | None, units: str, theme: str) -> None:
    here = place.label if place else ""
    with ui.row().classes("w-full items-center justify-between gap-4"):
        with ui.column().classes("gap-0"):
            ui.label("Weather now").classes("text-sm opacity-70")
            ui.label(here or "Weather now").classes("text-2xl font-semibold")
        with ui.column().classes("gap-0"):
            box = ui.input(placeholder="Search a city").props("dense clearable")
            hits = ui.column().classes("gap-0")

        async def suggest() -> None:
            hits.clear()
            text = (box.value or "").strip()
            if len(text) < 2:
                return
            try:
                places = await api.search(text)
            except om.UpstreamError:
                return
            with hits:
                if not places:
                    ui.label(f"No place called '{text}'").classes("text-sm")
                for p in places:
                    ui.button(p.label, on_click=lambda p=p: ui.navigate.to(url(p.label, units, theme))
                              ).props("flat dense no-caps")

        box.on("update:model-value", suggest, throttle=0.4)
        ui.toggle({"metric": "°C", "imperial": "°F"}, value=units,
                  on_change=lambda e: ui.navigate.to(url(here, e.value, theme)))
        ui.switch("Dark", value=theme == "dark",
                  on_change=lambda e: ui.navigate.to(url(here, units, "dark" if e.value else "light")))


def render_now(r: om.Result, units: str) -> None:
    c, u = r.data["current"], charts.UNIT_LABELS[units]
    text, icon = charts.weather(c["weather_code"])
    with ui.card().classes("w-full"):
        with ui.row().classes("items-center gap-4"):
            ui.icon(icon).classes("text-6xl")
            ui.label(f"{round(c['temperature_2m'])}{u['temp']}").classes("text-6xl font-semibold")
            ui.label(text).classes("text-xl")
        with ui.row().classes("gap-6"):
            for label, value in (("Feels like", f"{round(c['apparent_temperature'])}{u['temp']}"),
                                 ("Wind", f"{round(c['wind_speed_10m'])} {u['wind']}"),
                                 ("Humidity", f"{c['relative_humidity_2m']} %"),
                                 ("Precipitation", f"{c['precipitation']} {u['precip']}")):
                with ui.column().classes("gap-0"):
                    ui.label(label).classes("text-sm opacity-70")
                    ui.label(value).classes("text-lg")
        ui.label(f"{stamp(r, r.data.get('utc_offset_seconds', 0))} · times in "
                 f"{r.data.get('timezone', 'local time')}").classes("text-sm opacity-70")


def render_week(r: om.Result, units: str, theme: str) -> None:
    daily = r.data["daily"]
    ui.label("Next 7 days").classes("text-xl font-semibold")
    chart_or_table([charts.daily_range_option(daily, units, theme),
                    charts.precip_option(daily, theme)],
                   charts.DAILY_COLUMNS, charts.daily_rows(daily, units))


def render_fan(r: om.Result, units: str, theme: str) -> None:
    pct = charts.ensemble_percentiles(r.data["hourly"])
    ui.label("How sure is the forecast?").classes("text-xl font-semibold")
    ui.label("51 runs of the ECMWF ensemble. The wider the band, the less the runs agree.").classes(
        "text-sm opacity-70")
    ui.label(charts.spread_caption(pct))
    chart_or_table([charts.fan_option(pct, units, theme)], charts.FAN_COLUMNS,
                   charts.fan_rows(pct, units))


def render_air(r: om.Result, theme: str) -> None:
    cur = r.data["current"]
    ui.label("Air quality").classes("text-xl font-semibold")
    aqi = cur.get("european_aqi")
    if aqi is None:
        ui.label("No air-quality reading for this place.")
    else:
        name, status = charts.aqi_band(aqi)
        colour = charts.STATUS[status]
        with ui.row().classes("items-center gap-2"):
            ui.icon(charts.STATUS_ICON[status]).style(f"color: {colour}").classes("text-3xl")
            ui.label(f"European AQI {round(aqi)} · {name}").classes("text-lg")
        ui.linear_progress(value=min(aqi, 100) / 100, show_value=False, color=colour)
    pollen = [(label, cur.get(key)) for label, key in (("Birch pollen", "birch_pollen"),
                                                       ("Grass pollen", "grass_pollen"),
                                                       ("Ragweed pollen", "ragweed_pollen"))]
    with ui.row().classes("gap-6"):
        if cur.get("pm2_5") is not None:
            with ui.column().classes("gap-0"):
                ui.label("PM2.5").classes("text-sm opacity-70")
                ui.label(f"{cur['pm2_5']} µg/m³").classes("text-lg")
        for label, value in pollen:
            if value is not None:
                with ui.column().classes("gap-0"):
                    ui.label(label).classes("text-sm opacity-70")
                    ui.label(f"{value} grains/m³").classes("text-lg")
    chart_or_table([charts.aqi_option(r.data["hourly"], theme)], charts.AQI_COLUMNS,
                   charts.aqi_rows(r.data["hourly"]))


def footer() -> None:
    with ui.row().classes("w-full gap-2 text-sm opacity-70 pt-6"):
        ui.link("Weather data by Open-Meteo.com", "https://open-meteo.com/", new_tab=True)
        ui.label("·")
        ui.link("CC BY 4.0", "https://creativecommons.org/licenses/by/4.0/", new_tab=True)
        ui.label("·")
        ui.link("Places from GeoNames", "https://www.geonames.org/", new_tab=True)
        ui.label("·")
        ui.link("Source", "https://github.com/rationislabs/weather-live-dashboard", new_tab=True)


@ui.page("/")
async def index(city: str = "", units: str = "metric", theme: str = "light") -> None:
    settings = config.load()
    units = units if units in om.UNIT_PARAMS else "metric"
    theme = theme if theme in charts.PALETTE else "light"
    ui.dark_mode(theme == "dark")
    ui.query("body").style(f"background: {charts.PALETTE[theme]['surface']}")

    place, notice = await resolve(city, settings.default_city)
    with ui.column().classes("w-full max-w-5xl mx-auto p-4 gap-6"):
        header(place, units, theme)
        if notice:
            ui.label(notice).classes("text-sm")
        if place is None:
            ui.label("Couldn't reach the weather service.")
            ui.button("Retry", on_click=ui.navigate.reload)
            footer()
            return

        # Warm the cache in parallel; each panel then reads its own result and
        # fails on its own.
        await asyncio.gather(api.forecast(place, units), api.ensemble(place, units),
                             api.air(place), return_exceptions=True)
        now = panel("current conditions", lambda: api.forecast(place, units),
                    lambda r: render_now(r, units))
        await now()
        ui.timer(settings.cache_ttl, now.refresh)
        await panel("the 7-day forecast", lambda: api.forecast(place, units),
                    lambda r: render_week(r, units, theme))()
        await panel("the forecast spread", lambda: api.ensemble(place, units),
                    lambda r: render_fan(r, units, theme))()
        await panel("air quality", lambda: api.air(place), lambda r: render_air(r, theme))()
        footer()

    if not city:
        async def from_browser() -> None:
            """No ?city=: use the city the visitor's time zone names, if it is real."""
            try:
                tz = await ui.run_javascript("Intl.DateTimeFormat().resolvedOptions().timeZone",
                                             timeout=3)
            except Exception:  # noqa: BLE001 — no browser answer just keeps the default
                return
            guess = om.city_from_timezone(tz or "")
            if guess and guess.lower() != settings.default_city.lower() and await _find(guess):
                ui.navigate.to(url(guess, units, theme))

        ui.timer(0.1, from_browser, once=True)
