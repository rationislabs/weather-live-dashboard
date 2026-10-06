"""The one page. Layout and URL state only: data comes from openmeteo.py and
chart options from charts.py."""

from __future__ import annotations

from nicegui import ui


@ui.page("/")
async def index() -> None:
    ui.label("Weather now").classes("text-2xl font-semibold")
