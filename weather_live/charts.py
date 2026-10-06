"""API JSON in, chart data and ECharts option dicts out.

No NiceGUI and no network, so everything here is tested on recorded
responses. Colours follow the dataviz rules: one blue hue for magnitude,
stepped separately for light and dark (validated with validate_palette.py
--ordinal), and the reserved status colours only for air-quality bands,
always next to the band's name and an icon.
"""

from __future__ import annotations

import json
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


FONT = "system-ui, -apple-system, 'Segoe UI', sans-serif"

DAILY_COLUMNS = [{"name": "day", "label": "Day", "field": "day", "align": "left"},
                 {"name": "low", "label": "Low", "field": "low"},
                 {"name": "high", "label": "High", "field": "high"},
                 {"name": "rain", "label": "Chance of rain", "field": "rain"}]
FAN_COLUMNS = [{"name": "day", "label": "Day", "field": "day", "align": "left"},
               {"name": "low", "label": "Coldest likely (p10)", "field": "low"},
               {"name": "median", "label": "Median", "field": "median"},
               {"name": "high", "label": "Warmest likely (p90)", "field": "high"}]
AQI_COLUMNS = [{"name": "time", "label": "Time", "field": "time", "align": "left"},
               {"name": "aqi", "label": "European AQI", "field": "aqi"},
               {"name": "band", "label": "Band", "field": "band"}]


def _day(iso: str) -> str:
    return f"{date.fromisoformat(iso[:10]):%a %d}"


def _hour(iso: str) -> str:
    return f"{_day(iso)} {iso[11:16]}"


def _frame(theme: str) -> dict:
    p = PALETTE[theme]
    return {"backgroundColor": p["surface"], "animationDuration": 300,
            "textStyle": {"color": p["ink2"], "fontFamily": FONT},
            "grid": {"left": 48, "right": 16, "top": 36, "bottom": 32, "containLabel": True}}


def _axis(theme: str, **extra) -> dict:
    p = PALETTE[theme]
    return {"axisLine": {"lineStyle": {"color": p["axis"]}},
            "axisLabel": {"color": p["muted"]},
            "splitLine": {"lineStyle": {"color": p["grid"]}},
            "nameTextStyle": {"color": p["muted"]}, **extra}


def _tooltip(labels: list[str]) -> dict:
    """Axis tooltip whose text is computed here, so no chart logic lives in JS.
    The ':' prefix makes NiceGUI evaluate the value as JavaScript."""
    return {"trigger": "axis", ":formatter": f"p => {json.dumps(labels)}[p[0].dataIndex]"}


def _fmt(v, unit: str) -> str:
    return "–" if v is None else f"{round(v)}{unit}"


def daily_range_option(daily: dict, units: str, theme: str) -> dict:
    """Min–max per day as a range bar. A candlestick with open = low and
    close = high draws exactly the bar, including below zero."""
    p, u = PALETTE[theme], UNIT_LABELS[units]["temp"]
    lows, highs = daily["temperature_2m_min"], daily["temperature_2m_max"]
    days = [_day(d) for d in daily["time"]]
    labels = [f"{d}: {_fmt(lo, u)} to {_fmt(hi, u)}"
              for d, lo, hi in zip(days, lows, highs, strict=False)]
    colour = p["inner"]
    return {**_frame(theme), "tooltip": _tooltip(labels),
            "xAxis": _axis(theme, type="category", data=days),
            "yAxis": _axis(theme, type="value", scale=True, name=f"Temperature ({u})"),
            "series": [{"type": "candlestick", "name": "Temperature range", "barWidth": "40%",
                        "data": [[lo, hi, lo, hi] for lo, hi in zip(lows, highs, strict=False)],
                        "itemStyle": {"color": colour, "color0": colour, "borderColor": colour,
                                      "borderColor0": colour, "borderRadius": 4}}]}


def precip_option(daily: dict, theme: str) -> dict:
    p = PALETTE[theme]
    probs = daily["precipitation_probability_max"]
    days = [_day(d) for d in daily["time"]]
    labels = [f"{d}: {'–' if v is None else f'{v} %'} chance of rain"
              for d, v in zip(days, probs, strict=False)]
    return {**_frame(theme), "tooltip": _tooltip(labels),
            "xAxis": _axis(theme, type="category", data=days),
            "yAxis": _axis(theme, type="value", min=0, max=100, name="Chance of rain (%)"),
            "series": [{"type": "bar", "name": "Chance of rain", "data": probs, "barWidth": "40%",
                        "itemStyle": {"color": p["inner"], "borderRadius": [4, 4, 0, 0]}}]}


def _diff(lower: list, upper: list) -> list:
    return [None if a is None or b is None else round(b - a, 2)
            for a, b in zip(lower, upper, strict=False)]


def fan_option(pct: dict, units: str, theme: str) -> dict:
    """Two stacked bands (p10–p90 light, p25–p75 darker) and the median line.
    Each band is an invisible base series plus the band's width stacked on
    it; stackStrategy "all" keeps negative bases stacking."""
    p, u = PALETTE[theme], UNIT_LABELS[units]["temp"]
    hours = [_hour(t) for t in pct["time"]]
    labels = [f"{h}: median {_fmt(m, u)}, middle half {_fmt(a, u)} to {_fmt(b, u)}, "
              f"likely range {_fmt(lo, u)} to {_fmt(hi, u)}"
              for h, m, a, b, lo, hi in zip(hours, pct["p50"], pct["p25"], pct["p75"],
                                            pct["p10"], pct["p90"], strict=False)]

    def base(name: str, data: list, stack: str) -> dict:
        return {"name": name, "type": "line", "data": data, "stack": stack,
                "stackStrategy": "all", "symbol": "none", "lineStyle": {"opacity": 0}}

    def band(name: str, data: list, stack: str, colour: str) -> dict:
        return {**base(name, data, stack), "areaStyle": {"color": colour, "opacity": 1}}

    return {**_frame(theme), "tooltip": _tooltip(labels),
            "legend": {"data": ["10–90 %", "25–75 %", "Median"], "top": 0,
                       "textStyle": {"color": p["ink2"]}},
            "xAxis": _axis(theme, type="category", data=hours, boundaryGap=False,
                           axisLabel={"color": p["muted"], "interval": 23}),
            "yAxis": _axis(theme, type="value", scale=True, name=f"Temperature ({u})"),
            "series": [
                base("p10", pct["p10"], "outer"),
                band("10–90 %", _diff(pct["p10"], pct["p90"]), "outer", p["outer"]),
                base("p25", pct["p25"], "inner"),
                band("25–75 %", _diff(pct["p25"], pct["p75"]), "inner", p["inner"]),
                {"name": "Median", "type": "line", "data": pct["p50"], "symbol": "none",
                 "lineStyle": {"color": p["line"], "width": 2}, "itemStyle": {"color": p["line"]}},
            ]}


def aqi_option(hourly: dict, theme: str) -> dict:
    p = PALETTE[theme]
    values = hourly["european_aqi"]
    hours = [_hour(t) for t in hourly["time"]]
    labels = [f"{h}: " + ("no reading" if v is None else f"AQI {round(v)}, {aqi_band(v)[0]}")
              for h, v in zip(hours, values, strict=False)]
    return {**_frame(theme), "tooltip": _tooltip(labels),
            "xAxis": _axis(theme, type="category", data=hours, boundaryGap=False,
                           axisLabel={"color": p["muted"], "interval": 23}),
            "yAxis": _axis(theme, type="value", min=0, name="European AQI"),
            "series": [{"type": "line", "name": "European AQI", "data": values, "symbol": "none",
                        "lineStyle": {"color": p["line"], "width": 2},
                        "itemStyle": {"color": p["line"]}}]}


def daily_rows(daily: dict, units: str) -> list[dict]:
    u = UNIT_LABELS[units]["temp"]
    return [{"day": _day(d), "low": _fmt(lo, u), "high": _fmt(hi, u),
             "rain": "–" if r is None else f"{r} %"}
            for d, lo, hi, r in zip(daily["time"], daily["temperature_2m_min"],
                                    daily["temperature_2m_max"],
                                    daily["precipitation_probability_max"], strict=False)]


def fan_rows(pct: dict, units: str) -> list[dict]:
    """One row per day: the coldest p10, the mean median and the warmest p90."""
    u = UNIT_LABELS[units]["temp"]
    days: dict[str, dict[str, list]] = {}
    for t, lo, mid, hi in zip(pct["time"], pct["p10"], pct["p50"], pct["p90"], strict=False):
        if None in (lo, mid, hi):
            continue
        d = days.setdefault(t[:10], {"lo": [], "mid": [], "hi": []})
        d["lo"].append(lo)
        d["mid"].append(mid)
        d["hi"].append(hi)
    return [{"day": _day(day), "low": _fmt(min(v["lo"]), u),
             "median": _fmt(sum(v["mid"]) / len(v["mid"]), u), "high": _fmt(max(v["hi"]), u)}
            for day, v in days.items()]


def aqi_rows(hourly: dict) -> list[dict]:
    """Every third hour, so the table stays readable."""
    return [{"time": _hour(t), "aqi": "–" if v is None else round(v),
             "band": "–" if v is None else aqi_band(v)[0]}
            for t, v in list(zip(hourly["time"], hourly["european_aqi"], strict=False))[::3]]
