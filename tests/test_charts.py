from weather_live import charts

WMO = (
    0,
    1,
    2,
    3,
    45,
    48,
    51,
    53,
    55,
    56,
    57,
    61,
    63,
    65,
    66,
    67,
    71,
    73,
    75,
    77,
    80,
    81,
    82,
    85,
    86,
    95,
    96,
    99,
)


def test_every_wmo_code_has_text_and_icon(fx):
    for code in WMO:
        text, icon = charts.weather(code)
        assert text and text != "Unknown" and icon, code
    assert charts.weather(1234) == ("Unknown", "help_outline")
    for code in fx("forecast_vienna")["daily"]["weather_code"]:
        assert charts.weather(code)[0] != "Unknown"


def test_aqi_bands_at_every_edge():
    cases = {
        0: "Good",
        20: "Good",
        20.1: "Fair",
        40: "Fair",
        40.5: "Moderate",
        60: "Moderate",
        61: "Poor",
        80: "Poor",
        81: "Very poor",
        100: "Very poor",
        100.1: "Extremely poor",
        500: "Extremely poor",
    }
    for value, name in cases.items():
        assert charts.aqi_band(value)[0] == name, value
    assert charts.aqi_band(10)[1] == "good" and charts.aqi_band(150)[1] == "critical"
    assert set(s for _, s in map(charts.aqi_band, cases)) <= set(charts.STATUS)


def test_percentiles_on_known_values():
    hourly = {
        "time": ["2026-10-05T00:00"],
        "temperature_2m": [0.0],
        **{f"temperature_2m_member{i:02d}": [float(i)] for i in range(1, 51)},
    }
    pct = charts.ensemble_percentiles(hourly)
    assert (pct["p10"][0], pct["p25"][0], pct["p50"][0], pct["p75"][0], pct["p90"][0]) == (
        5.0,
        12.5,
        25.0,
        37.5,
        45.0,
    )


def test_percentiles_on_the_recording_are_ordered(fx):
    pct = charts.ensemble_percentiles(fx("ensemble_vienna")["hourly"])
    assert len(pct["time"]) == 168
    for row in zip(pct["p10"], pct["p25"], pct["p50"], pct["p75"], pct["p90"], strict=True):
        assert list(row) == sorted(row)


def test_hours_with_missing_members_are_gaps():
    hourly = {
        "time": ["2026-10-05T00:00"],
        "temperature_2m": [None],
        "temperature_2m_member01": [3.0],
    }
    assert charts.ensemble_percentiles(hourly)["p50"] == [None]


def _pct(widths_per_day):
    """Hourly p10/p90 with a constant width per day."""
    pct = {"time": [], "p10": [], "p90": []}
    for d, w in enumerate(widths_per_day):
        for h in range(24):
            pct["time"].append(f"2026-10-{5 + d:02d}T{h:02d}:00")
            pct["p10"].append(0.0)
            pct["p90"].append(w)
    return pct


def test_spread_caption_names_the_first_doubling_day():
    # 2026-10-05 is a Monday; width doubles on day 4, Thursday 08
    caption = charts.spread_caption(_pct([1, 1.2, 1.5, 2.0, 3, 4, 5]))
    assert caption.startswith("The spread widens on Thursday")


def test_spread_caption_when_members_agree_and_when_short():
    assert charts.spread_caption(_pct([1, 1, 1, 1, 1, 1, 1])).startswith("The members agree")
    assert "covers 3 days" in charts.spread_caption(_pct([1, 1, 1]))
    assert (
        charts.spread_caption({"time": [], "p10": [], "p90": []})
        == "No ensemble data for this place."
    )
