from pathlib import Path

COMPOSE = (Path(__file__).resolve().parents[1] / "compose.yml").read_text()


def test_host_port_can_be_changed():
    # another app on the host may hold 8080: HOST_PORT=8085 docker compose up
    assert '"127.0.0.1:${HOST_PORT:-8080}:8080"' in COMPOSE
