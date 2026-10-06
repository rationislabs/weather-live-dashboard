from weather_live import config


def test_defaults(monkeypatch):
    for name in ("HOST", "PORT", "DEFAULT_CITY", "CACHE_TTL", "CACHE_MAX", "STALE_MAX"):
        monkeypatch.delenv(name, raising=False)
    s = config.load()
    assert s == config.Settings(
        host="127.0.0.1", port=8080, default_city="Vienna",
        cache_ttl=900, cache_max=500, stale_max=21600,
    )


def test_environment_overrides(monkeypatch):
    monkeypatch.setenv("PORT", "9000")
    monkeypatch.setenv("DEFAULT_CITY", "Graz")
    s = config.load()
    assert (s.port, s.default_city) == (9000, "Graz")
