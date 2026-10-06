"""Entry point: `python main.py` (Docker, `inv dev`). NiceGUI's test harness
also loads this file (`main_file` in pyproject.toml)."""

from nicegui import ui

from weather_live import config, page  # noqa: F401  (importing page registers "/")

if __name__ in {"__main__", "__mp_main__"}:
    settings = config.load()
    ui.run(host=settings.host, port=settings.port, title="Weather now", reload=False, show=False)
