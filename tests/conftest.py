import os
from pathlib import Path


def pytest_addoption(parser):
    parser.addoption(
        "--run-ml", action="store_true", help="Run pinned Quiteria model compatibility tests"
    )


def pytest_configure(config):
    # testcontainers (MiniStack nos testes de integração) usa o socket do OrbStack
    # quando ele existe; nos demais ambientes vale o DOCKER_HOST padrão.
    orbstack = Path.home() / ".orbstack" / "run" / "docker.sock"
    if orbstack.exists():
        os.environ.setdefault("DOCKER_HOST", f"unix://{orbstack}")
