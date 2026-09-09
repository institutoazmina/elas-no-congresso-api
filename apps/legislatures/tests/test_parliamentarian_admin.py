from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.contrib.messages import get_messages
from django.test import Client
from django.urls import reverse

from apps.subscriptions.models import Subscription
from config.api import api

pytestmark = pytest.mark.django_db

User = get_user_model()
ENRICHMENT_URL_NAME = "admin:legislatures_parliamentarian_enrich_profiles"
CHANGE_LIST_URL_NAME = "admin:legislatures_parliamentarian_changelist"
OLD_ENRICHMENT_URL = "/api/v1/ingestion/parliamentarian-enrichment-runs"


def make_staff_user(*, can_change=False):
    user = User.objects.create_user(username=f"staff-{User.objects.count()}")
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    if can_change:
        permission = Permission.objects.get(codename="change_parliamentarian")
        user.user_permissions.add(permission)
    return user


def test_anonymous_access_redirects_to_admin_login():
    response = Client().get(reverse(ENRICHMENT_URL_NAME))

    assert response.status_code == 302
    assert response.url.startswith(reverse("admin:login"))


def test_staff_without_change_permission_gets_forbidden():
    client = Client()
    client.force_login(make_staff_user())

    response = client.get(reverse(ENRICHMENT_URL_NAME))

    assert response.status_code == 403


def test_staff_with_change_permission_sees_confirmation_page():
    client = Client()
    client.force_login(make_staff_user(can_change=True))

    response = client.get(reverse(ENRICHMENT_URL_NAME))

    assert response.status_code == 200
    assert "Enriquecer perfis parlamentares" in response.content.decode()
    assert "Deseja iniciar" in response.content.decode()
    assert 'name="csrfmiddlewaretoken"' in response.content.decode()


def test_changelist_displays_manual_enrichment_button_for_permitted_staff():
    client = Client()
    client.force_login(make_staff_user(can_change=True))

    response = client.get(reverse(CHANGE_LIST_URL_NAME))

    assert response.status_code == 200
    assert reverse(ENRICHMENT_URL_NAME) in response.content.decode()
    assert "Atualizar perfis" in response.content.decode()


def test_post_queues_enrichment_once_shows_task_id_and_redirects():
    client = Client()
    client.force_login(make_staff_user(can_change=True))

    with patch("apps.ingestion.tasks.enrich_parliamentarian_profiles.delay") as delay:
        delay.return_value.id = "task-123"
        response = client.post(reverse(ENRICHMENT_URL_NAME))

    assert response.status_code == 302
    assert response.url == reverse(CHANGE_LIST_URL_NAME)
    delay.assert_called_once_with()
    assert any("task-123" in str(message) for message in get_messages(response.wsgi_request))


def test_manual_enrichment_post_requires_csrf_token():
    client = Client(enforce_csrf_checks=True)
    client.force_login(make_staff_user(can_change=True))

    with patch("apps.ingestion.tasks.enrich_parliamentarian_profiles.delay") as delay:
        response = client.post(reverse(ENRICHMENT_URL_NAME))

    assert response.status_code == 403
    delay.assert_not_called()


def test_old_enrichment_api_endpoint_is_gone():
    response = Client().post(OLD_ENRICHMENT_URL)

    assert response.status_code == 404


def test_openapi_has_no_enrichment_bearer_security_scheme_and_keeps_public_routes():
    schema = api.get_openapi_schema()

    assert OLD_ENRICHMENT_URL not in schema["paths"]
    assert "/api/v1/legislatures/parliamentarians" in schema["paths"]
    assert "security" not in schema["paths"]["/api/v1/legislatures/parliamentarians"]["get"]
    assert not any(
        scheme.get("type") == "http" and scheme.get("scheme") == "bearer"
        for scheme in schema.get("components", {}).get("securitySchemes", {}).values()
    )


def test_public_api_route_remains_unauthenticated():
    with patch(
        "apps.subscriptions.api.Subscription.objects.get",
        side_effect=Subscription.DoesNotExist,
    ):
        response = Client().get("/api/v1/subscriptions/confirm/not-a-token")

    assert response.status_code == 302
