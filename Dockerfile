# One container, configured from the environment, ready to host as-is.
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.15 /uv /bin/uv
RUN useradd --uid 10001 --create-home app
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY main.py ./
COPY weather_live ./weather_live
# NiceGUI writes .nicegui/ next to main.py at start-up.
RUN chown app:app /app
ENV PATH=/app/.venv/bin:$PATH HOST=0.0.0.0 PORT=8080
USER app
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s CMD \
  python -c "import os, urllib.request; urllib.request.urlopen(f'http://127.0.0.1:{os.environ[\"PORT\"]}/', timeout=4)"
CMD ["python", "main.py"]
