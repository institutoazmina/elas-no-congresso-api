"""Framework contracts that force_login and the default test client bypass."""

from unittest.mock import Mock

import pytest
from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from apps.subscriptions.models import Subscription

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def isolated_cache():
    cache.clear()
    yield
    cache.clear()


def test_admin_password_login_csrf_session_and_logout(settings):
    settings.SESSION_COOKIE_SECURE = True
    settings.CSRF_COOKIE_SECURE = True
    get_user_model().objects.create_user(
        username="compat-staff", password="test-password-only", is_staff=True
    )
    client = Client(enforce_csrf_checks=True)
    login = reverse("admin:login")
    index = reverse("admin:index")
    payload = {"username": "compat-staff", "password": "test-password-only", "next": index}
    assert client.get(login, secure=True).status_code == 200
    assert client.cookies[settings.CSRF_COOKIE_NAME]["secure"]
    assert client.post(login, payload, secure=True).status_code == 403
    payload["csrfmiddlewaretoken"] = client.cookies[settings.CSRF_COOKIE_NAME].value
    assert (
        client.post(
            login, payload, secure=True, HTTP_ORIGIN="https://untrusted.example"
        ).status_code
        == 403
    )
    response = client.post(login, payload, secure=True, HTTP_ORIGIN="https://testserver")
    assert response.status_code == 302
    assert response.url == index
    assert client.cookies[settings.SESSION_COOKIE_NAME]["secure"]
    response = client.get(index, secure=True)
    assert response.status_code == 200
    assert response.wsgi_request.user.username == "compat-staff"
    assert "public" not in response.get("Cache-Control", "")
    replay = Client()
    replay.cookies[settings.SESSION_COOKIE_NAME] = client.cookies[
        settings.SESSION_COOKIE_NAME
    ].value
    assert replay.get(index, secure=True).status_code == 200
    assert client.post(reverse("admin:logout"), secure=True).status_code == 403
    response = client.post(
        reverse("admin:logout"),
        {"csrfmiddlewaretoken": client.cookies[settings.CSRF_COOKIE_NAME].value},
        secure=True,
        HTTP_ORIGIN="https://testserver",
    )
    assert response.status_code == 200
    assert client.get(index, secure=True).status_code == 302
    assert replay.get(index, secure=True).status_code == 302


def test_non_staff_password_login_cannot_open_admin():
    get_user_model().objects.create_user(username="compat-reader", password="test-password-only")
    client = Client()
    assert client.login(username="compat-reader", password="test-password-only")
    response = client.get(reverse("admin:index"))
    assert response.status_code == 302
    assert reverse("admin:login") in response.url


@pytest.mark.parametrize(
    ("email", "expected"),
    [
        ("Pessoa@EXAMPLE.COM", "Pessoa@example.com"),
        ("Pessoa@bücher.de", "Pessoa@bücher.de"),
        ("Pessoa@xn--bcher-kva.de", "Pessoa@bücher.de"),
    ],
)
def test_subscription_email_normalization_survives_dependency_updates(email, expected, monkeypatch):
    send = Mock()
    monkeypatch.setattr("apps.subscriptions.tasks.send_confirmation_email.delay", send)
    response = Client(enforce_csrf_checks=True).post(
        "/api/v1/subscriptions/",
        {
            "email": email,
            "accepted_terms": True,
            "alerts": [
                {"frequency": "daily", "ast": {"field": "casa", "op": "eq", "value": "camara"}}
            ],
        },
        content_type="application/json",
    )
    assert response.status_code == 201, response.content
    sub = Subscription.objects.get()
    assert sub.email == expected
    assert response.json()[0]["email"] == expected
    assert sub.is_active is False
    send.assert_called_once_with(sub.pk)


@pytest.mark.parametrize("email", ["not-an-address", "user@" + "a" * 254 + ".com"])
def test_invalid_subscription_email_has_no_side_effects(email, monkeypatch):
    send = Mock()
    monkeypatch.setattr("apps.subscriptions.tasks.send_confirmation_email.delay", send)
    response = Client().post(
        "/api/v1/subscriptions/",
        {
            "email": email,
            "accepted_terms": True,
            "alerts": [
                {"frequency": "daily", "ast": {"field": "casa", "op": "eq", "value": "camara"}}
            ],
        },
        content_type="application/json",
    )
    assert response.status_code == 422
    assert not Subscription.objects.exists()
    send.assert_not_called()
