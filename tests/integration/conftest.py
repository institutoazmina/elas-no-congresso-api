import time
import urllib.request

import boto3
import pytest
from testcontainers.core.container import DockerContainer


@pytest.fixture(scope="session")
def ministack_container():
    from django.conf import settings

    container = DockerContainer("nahuelnucera/ministack").with_exposed_ports(4566)
    container.start()
    port = container.get_exposed_port(4566)
    settings.AWS_SES_ENDPOINT_URL = f"http://localhost:{port}"

    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            urllib.request.urlopen(f"http://localhost:{port}/_localstack/health")
            break
        except Exception:
            time.sleep(0.5)

    yield container
    container.stop()


@pytest.fixture(scope="session")
def ses_client(ministack_container):
    from django.conf import settings

    return boto3.client(
        "sesv2",
        endpoint_url=settings.AWS_SES_ENDPOINT_URL,
        aws_access_key_id="test",
        aws_secret_access_key="test",
        region_name="us-east-1",
    )


@pytest.fixture(scope="session")
def verified_sender(ses_client):
    from django.conf import settings

    ses_client.create_email_identity(EmailIdentity=settings.AWS_SES_FROM_EMAIL)
