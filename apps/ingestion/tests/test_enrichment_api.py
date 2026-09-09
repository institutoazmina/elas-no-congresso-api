from unittest.mock import patch

from django.test import Client, override_settings

from apps.subscriptions.models import Subscription
from config.api import api

ENRICHMENT_URL = "/api/v1/ingestion/parliamentarian-enrichment-runs"
TOKEN = "test-parliamentarian-enrichment-token"


def test_valid_bearer_token_queues_enrichment_and_returns_task_id():
    with patch("apps.ingestion.tasks.enrich_parliamentarian_profiles.delay") as delay:
        delay.return_value.id = "task-123"

        response = Client(enforce_csrf_checks=True).post(
            ENRICHMENT_URL,
            HTTP_AUTHORIZATION=f"Bearer {TOKEN}",
        )

    assert response.status_code == 202
    assert response.json() == {"status": "queued", "task_id": "task-123"}
    delay.assert_called_once_with()


def test_missing_bearer_token_is_rejected():
    with patch("apps.ingestion.tasks.enrich_parliamentarian_profiles.delay") as delay:
        response = Client().post(ENRICHMENT_URL)

    assert response.status_code == 401
    delay.assert_not_called()


def test_wrong_bearer_token_is_rejected():
    with patch("apps.ingestion.tasks.enrich_parliamentarian_profiles.delay") as delay:
        response = Client().post(
            ENRICHMENT_URL,
            HTTP_AUTHORIZATION="Bearer wrong-token",
        )

    assert response.status_code == 401
    delay.assert_not_called()


@override_settings(PARLIAMENTARIAN_ENRICHMENT_API_TOKEN="")
def test_unconfigured_token_fails_closed_even_when_secret_key_is_set():
    with (
        override_settings(SECRET_KEY="secret-key-must-not-be-reused"),
        patch("apps.ingestion.tasks.enrich_parliamentarian_profiles.delay") as delay,
    ):
        response = Client().post(
            ENRICHMENT_URL,
            HTTP_AUTHORIZATION="Bearer secret-key-must-not-be-reused",
        )

    assert response.status_code == 401
    delay.assert_not_called()


def test_public_route_remains_unauthenticated():
    with patch(
        "apps.subscriptions.api.Subscription.objects.get",
        side_effect=Subscription.DoesNotExist,
    ):
        response = Client().get("/api/v1/subscriptions/confirm/not-a-token")

    assert response.status_code == 302


def test_openapi_documents_bearer_auth_only_for_enrichment_operation():
    schema = api.get_openapi_schema()
    protected_operation = schema["paths"][ENRICHMENT_URL]["post"]
    public_operation = schema["paths"]["/api/v1/legislatures/parliamentarians"]["get"]

    assert protected_operation["security"]
    assert "security" not in public_operation
    secured_operations = {
        (path, method)
        for path, path_item in schema["paths"].items()
        for method, operation in path_item.items()
        if method in {"get", "post", "put", "patch", "delete"} and operation.get("security")
    }
    assert secured_operations == {(ENRICHMENT_URL, "post")}
    assert any(
        scheme.get("type") == "http" and scheme.get("scheme") == "bearer"
        for scheme in schema["components"]["securitySchemes"].values()
    )
