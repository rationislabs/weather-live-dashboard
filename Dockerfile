# One container, configured from the environment, ready to host as-is.
# uv as a stage of its own: Dependabot's docker updates read FROM lines.
FROM ghcr.io/astral-sh/uv:0.13.5@sha256:32a7bb39b496babbd997b0a39a4d66c126bdaf5661b302bf6f06abda8deca6ff AS uv
FROM python:3.12-slim@sha256:cb33f7f771ecec2ef1225cf39b159591a040391bd73e4c01f00fdfc4c47611d2
COPY --from=uv /uv /bin/uv
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
