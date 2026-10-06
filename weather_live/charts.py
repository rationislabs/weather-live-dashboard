"""API JSON in, chart data and ECharts option dicts out.

No NiceGUI and no network, so everything here is tested on recorded
responses. Colours follow the dataviz rules: one blue hue for magnitude,
stepped separately for light and dark (validated with validate_palette.py
--ordinal), and the reserved status colours only for air-quality bands,
always next to the band's name and an icon.
"""

from __future__ import annotations

import statistics
from datetime import date

PALETTE: dict[str, dict[str, str]] = {
    "light": {"surface": "#fcfcfb", "ink": "#0b0b0b", "ink2": "#52514e", "muted": "#898781",
              "grid": "#e1e0d9", "axis": "#c3c2b7",
              "outer": "#86b6ef", "inner": "#3987e5", "line": "#1c5cab"},
    "dark": {"surface": "#1a1a19", "ink": "#ffffff", "ink2": "#c3c2b7", "muted": "#898781",
             "grid": "#2c2c2a", "axis": "#383835",
             "outer": "#184f95", "inner": "#2a78d6", "line": "#86b6ef"},
}
STATUS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}
STATUS_ICON = {"good": "sentiment_satisfied", "warning": "sentiment_neutral",
               "serious": "sentiment_dissatisfied", "critical": "warning"}
UNIT_LABELS = {"metric": {"temp": "°C", "wind": "km/h", "precip": "mm"},
               "imperial": {"temp": "°F", "wind": "mph", "precip": "in"}}

# WMO weather interpretation codes, as Open-Meteo documents them.
WEATHER_CODES: dict[int, tuple[str, str]] = {
    0: ("Clear sky", "wb_sunny"), 1: ("Mainly clear", "wb_sunny"),
    2: ("Partly cloudy", "wb_cloudy"), 3: ("Overcast", "cloud"),
    45: ("Fog", "blur_on"), 48: ("Freezing fog", "blur_on"),
    51: ("Light drizzle", "grain"), 53: ("Drizzle", "grain"), 55: ("Dense drizzle", "grain"),
    56: ("Light freezing drizzle", "grain"), 57: ("Freezing drizzle", "grain"),
    61: ("Light rain", "water_drop"), 63: ("Rain", "water_drop"), 65: ("Heavy rain", "water_drop"),
    66: ("Light freezing rain", "water_drop"), 67: ("Freezing rain", "water_drop"),
    71: ("Light snow", "ac_unit"), 73: ("Snow", "ac_unit"), 75: ("Heavy snow", "ac_unit"),
    77: ("Snow grains", "ac_unit"),
    80: ("Light showers", "water_drop"), 81: ("Showers", "water_drop"),
    82: ("Violent showers", "water_drop"),
    85: ("Light snow showers", "ac_unit"), 86: ("Snow showers", "ac_unit"),
    95: ("Thunderstorm", "thunderstorm"), 96: ("Thunderstorm with hail", "thunderstorm"),
    99: ("Thunderstorm with heavy hail", "thunderstorm"),
}

# European AQI bands; each upper edge belongs to its band (20 is Good).
AQI_BANDS = ((20, "Good", "good"), (40, "Fair", "good"), (60, "Moderate", "warning"),
             (80, "Poor", "serious"), (100, "Very poor", "critical"))

# statistics.quantiles(n=20) returns 19 cut points at 5 %, 10 %, ... 95 %.
QUANTILES = {"p10": 1, "p25": 4, "p50": 9, "p75": 14, "p90": 17}


def weather(code: int) -> tuple[str, str]:
    return WEATHER_CODES.get(code, ("Unknown", "help_outline"))


def aqi_band(value: float) -> tuple[str, str]:
    for upper, name, status in AQI_BANDS:
        if value <= upper:
            return name, status
    return "Extremely poor", "critical"


def ensemble_percentiles(hourly: dict) -> dict[str, list]:
    """Per hour, the 10/25/50/75/90th percentile over every ensemble member
    (the control plus `temperature_2m_memberNN`, however many arrive). An hour
    with fewer than two values is a gap (None)."""
    members = [v for k, v in hourly.items()
               if k == "temperature_2m" or k.startswith("temperature_2m_member")]
    out: dict[str, list] = {"time": list(hourly["time"]), **{q: [] for q in QUANTILES}}
    for i in range(len(hourly["time"])):
        values = [m[i] for m in members if m[i] is not None]
        if len(values) < 2:
            for q in QUANTILES:
                out[q].append(None)
            continue
        cuts = statistics.quantiles(values, n=20, method="inclusive")
        for q, idx in QUANTILES.items():
            out[q].append(round(cuts[idx], 2))
    return out


def spread_caption(pct: dict) -> str:
    """Names the first day whose mean p10–p90 width is at least twice the first day's."""
    days: dict[str, list[float]] = {}
    for t, lo, hi in zip(pct["time"], pct["p10"], pct["p90"], strict=False):
        if lo is not None and hi is not None:
            days.setdefault(t[:10], []).append(hi - lo)
    widths = [(d, sum(w) / len(w)) for d, w in days.items()]
    if not widths:
        return "No ensemble data for this place."
    note = "" if len(widths) >= 7 else f" The ensemble covers {len(widths)} days."
    base = widths[0][1]
    for d, w in widths[1:]:
        if (base > 0 and w >= 2 * base) or (base == 0 and w > 0):
            day = date.fromisoformat(d)
            return f"The spread widens on {day:%A}: the forecast is less certain from then.{note}"
    return f"The members agree all week: a confident forecast.{note}"
