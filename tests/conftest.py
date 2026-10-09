import os
from pathlib import Path


def pytest_configure(config):
    # testcontainers (MiniStack nos testes de integração) usa o socket do OrbStack
    # quando ele existe; nos demais ambientes vale o DOCKER_HOST padrão.
    orbstack = Path.home() / ".orbstack" / "run" / "docker.sock"
    if orbstack.exists():
        os.environ.setdefault("DOCKER_HOST", f"unix://{orbstack}")
