# weather-live-dashboard

Live weather for one city: current conditions, the next 7 days, how sure the forecast is, and
air quality. Built with [NiceGUI](https://nicegui.io) and ECharts.

The centrepiece is the **forecast spread**: 51 runs of the ECMWF ensemble, drawn as bands. The
wider the band, the less the runs agree, so you can see which days the forecast is confident
about and which it is guessing.

<!-- screenshots: light, dark, phone -->

## Run it

With Docker:

```bash
docker compose up -d --build
# open http://127.0.0.1:8080/?city=Vienna
docker compose down
```

If port 8080 is taken, pick another: `HOST_PORT=8085 docker compose up -d --build`.

For development (needs [uv](https://docs.astral.sh/uv/)):

```bash
uv sync
uv run inv dev      # http://127.0.0.1:8080
uv run inv test     # offline, on recorded responses
uv run inv lint
uv run inv e2e      # one run against the real API
uv run inv fixtures # re-record the test responses
```

## Watching the containers

To watch the containers, images, volumes and logs in a terminal UI, run [lazydocker](https://github.com/jesseduffield/lazydocker) (optional):

```bash
lazydocker
```

## Links and settings

The URL holds the whole view, so a link opens the same thing:
`/?city=Springfield, Missouri, US&units=imperial&theme=dark`.

| Variable | Default | Meaning |
|---|---|---|
| `HOST` | `127.0.0.1` (`0.0.0.0` in the image) | Address to listen on |
| `PORT` | `8080` | Port |
| `DEFAULT_CITY` | `Vienna` | City when the link names none and the browser's time zone names no city |
| `CACHE_TTL` | `900` | Seconds a response is fresh (Open-Meteo updates every 15 minutes) |
| `CACHE_MAX` | `500` | Cached responses kept |
| `STALE_MAX` | `21600` | Seconds an old response may be shown when the API fails |

## How it holds up

- Each panel loads on its own; one failing API shows Retry in that panel only.
- Responses are cached for 15 minutes, shared between visitors, and served stale for up to 6
  hours if the API fails. After an HTTP 429 the app waits 60 seconds before asking again.

## Data

[Weather data by Open-Meteo.com](https://open-meteo.com/), licensed
[CC BY 4.0](https://creativecommons.org/licenses/by/4.0/). Place search uses
[GeoNames](https://www.geonames.org/) through Open-Meteo's geocoding API.
