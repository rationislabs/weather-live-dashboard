from weather_live import charts


def test_daily_range_has_seven_days_and_one_axis(fx):
    daily = fx("forecast_vienna")["daily"]
    opt = charts.daily_range_option(daily, "metric", "light")
    assert len(opt["xAxis"]["data"]) == 7
    assert isinstance(opt["yAxis"], dict), "never a second y-axis"
    lo, hi = daily["temperature_2m_min"][0], daily["temperature_2m_max"][0]
    assert opt["series"][0]["data"][0] == [lo, hi, lo, hi]
    assert "°C" in opt["yAxis"]["name"]


def test_tooltips_are_precomputed_text(fx):
    opt = charts.precip_option(fx("forecast_vienna")["daily"], "light")
    formatter = opt["tooltip"][":formatter"]
    assert formatter.startswith("p => [") and "dataIndex" in formatter


def test_fan_has_two_bands_and_a_median(fx):
    pct = charts.ensemble_percentiles(fx("ensemble_vienna")["hourly"])
    opt = charts.fan_option(pct, "metric", "dark")
    names = [s["name"] for s in opt["series"]]
    assert names == ["p10", "10–90 %", "p25", "25–75 %", "Median"]
    assert opt["series"][1]["areaStyle"]["color"] == charts.PALETTE["dark"]["outer"]
    assert opt["backgroundColor"] == charts.PALETTE["dark"]["surface"]
    assert opt["legend"]["data"] == ["10–90 %", "25–75 %", "Median"]


def test_fan_stacks_across_zero():
    pct = {
        "time": ["2026-01-10T00:00", "2026-01-10T01:00"],
        "p10": [-31.0, -30.0],
        "p25": [-29.0, -28.5],
        "p50": [-27.0, -26.0],
        "p75": [-25.0, -24.0],
        "p90": [-22.0, 1.0],
    }
    opt = charts.fan_option(pct, "metric", "light")
    by = {s["name"]: s for s in opt["series"]}
    assert by["10–90 %"]["data"] == [9.0, 31.0]
    assert by["25–75 %"]["data"] == [4.0, 4.5]
    for name in ("p10", "10–90 %", "p25", "25–75 %"):
        assert by[name]["stackStrategy"] == "all", "negative bases must still stack"


def test_aqi_line_and_rows(fx):
    hourly = fx("air_vienna")["hourly"]
    opt = charts.aqi_option(hourly, "light")
    assert len(opt["series"][0]["data"]) == len(hourly["time"])
    rows = charts.aqi_rows(hourly)
    assert rows and set(rows[0]) == {c["field"] for c in charts.AQI_COLUMNS}


def test_table_rows_match_their_columns(fx):
    daily = fx("forecast_vienna")["daily"]
    rows = charts.daily_rows(daily, "imperial")
    assert len(rows) == 7 and set(rows[0]) == {c["field"] for c in charts.DAILY_COLUMNS}
    assert rows[0]["low"].endswith("°F")
    pct = charts.ensemble_percentiles(fx("ensemble_vienna")["hourly"])
    fan = charts.fan_rows(pct, "metric")
    assert len(fan) == 7 and set(fan[0]) == {c["field"] for c in charts.FAN_COLUMNS}


def test_fan_legend_swatches_match_the_bands(fx):
    pct = charts.ensemble_percentiles(fx("ensemble_vienna")["hourly"])
    by = {s["name"]: s for s in charts.fan_option(pct, "metric", "light")["series"]}
    assert by["10–90 %"]["itemStyle"]["color"] == charts.PALETTE["light"]["outer"]
    assert by["25–75 %"]["itemStyle"]["color"] == charts.PALETTE["light"]["inner"]


def test_hourly_axes_label_days_only_and_hide_overlaps(fx):
    pct = charts.ensemble_percentiles(fx("ensemble_vienna")["hourly"])
    for opt in (
        charts.fan_option(pct, "metric", "light"),
        charts.aqi_option(fx("air_vienna")["hourly"], "light"),
    ):
        label = opt["xAxis"]["axisLabel"]
        assert label["hideOverlap"] is True and label[":formatter"] == "v => v.slice(0, 6)"
    fan = charts.fan_option(pct, "metric", "light")
    assert fan["grid"]["top"] >= 56, "legend needs its own row above the axis title"


def test_tooltip_text_is_html_escaped(fx):
    """ECharts renders tooltip text as HTML."""
    daily = fx("forecast_vienna")["daily"]
    daily["precipitation_probability_max"][0] = "<img src=x onerror=alert(1)>"
    formatter = charts.precip_option(daily, "light")["tooltip"][":formatter"]
    assert "<img" not in formatter and "&lt;img" in formatter


def test_search_throttle_is_enforced_on_the_server():
    from weather_live import openmeteo as om

    seen: dict = {}
    assert om.allow_search(seen, now=100.0) is True
    assert om.allow_search(seen, now=100.2) is False
    assert om.allow_search(seen, now=100.5) is True


def test_one_client_gets_only_part_of_the_shared_lookup_budget():
    # 0.3 s apart is still ~200 a minute: one tab could use everyone's Open-Meteo budget.
    from weather_live import openmeteo as om

    seen: dict = {}
    allowed = [om.allow_search(seen, now=1000.0 + i) for i in range(40)]  # one a second
    assert allowed == [True] * om.SEARCHES_PER_MINUTE + [False] * (40 - om.SEARCHES_PER_MINUTE)
    assert om.allow_search(seen, now=1061.0) is True
