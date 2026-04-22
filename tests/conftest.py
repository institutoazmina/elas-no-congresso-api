import os
import subprocess
import uuid
from pathlib import Path

import pytest


def pytest_configure(config):
    def docker_host():
        orbstack = Path.home() / ".orbstack" / "run" / "docker.sock"
        if orbstack.exists():
            return f"unix://{orbstack}"
        return None

    dh = docker_host()
    if dh:
        os.environ["DOCKER_HOST"] = dh

    try:
        subprocess.run(["docker", "info"], check=True, capture_output=True)
        config._docker_available = True
    except Exception:
        config._docker_available = False


@pytest.fixture(scope="session")
def pg_dsn():
    if not hasattr(pytest.config, "_docker_available") or not pytest.config._docker_available:
        pytest.skip("Docker not available")

    from testcontainers.postgres import PostgresContainer

    with PostgresContainer("pgvector/pgvector:pg16") as pg:
        yield pg.get_connection_url().replace("postgresql+psycopg2://", "postgresql://")


@pytest.fixture(scope="session")
def django_db(pg_dsn):
    os.environ["TEST_DATABASE_URL"] = pg_dsn

    from django.core.management import call_command

    call_command("migrate", verbosity=0)

    yield pg_dsn

    call_command("flush", verbosity=0, interactive=False)