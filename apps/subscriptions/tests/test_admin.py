import datetime
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.test import Client
from django.urls import reverse

from apps.propositions.models import Proposition
from apps.subscriptions.models import Subscription

pytestmark = pytest.mark.django_db

User = get_user_model()


def _staff_with_subscription_change_permission():
    user = User.objects.create_user(username=f"staff-{User.objects.count()}")
    user.is_staff = True
    user.save(update_fields=["is_staff"])
    user.user_permissions.add(Permission.objects.get(codename="change_subscription"))
    return user


def _subscription(**kwargs):
    defaults = {
        "email": "teste@example.org",
        "frequency": "daily",
        "ast": {"field": "casa", "op": "eq", "value": "camara"},
        "query": "casa_camara",
        "is_active": True,
    }
    defaults.update(kwargs)
    return Subscription.objects.create(**defaults)


def _proposition(**kwargs):
    defaults = {
        "house": "camara",
        "external_id": 999,
        "type_code": "pl",
        "number_label": "PL de teste 1/2026",
        "number": 1,
        "year": 2026,
        "presented_at": datetime.date(2026, 1, 1),
        "ementa": "Proposição usada no alerta de teste.",
        "current_status": "Em tramitação",
    }
    defaults.update(kwargs)
    return Proposition.objects.create(**defaults)


def _url(subscription):
    return reverse("admin:subscriptions_subscription_send_test_alert", args=[subscription.pk])


def test_active_subscription_shows_test_alert_button():
    subscription = _subscription()
    client = Client()
    client.force_login(_staff_with_subscription_change_permission())

    response = client.get(
        reverse("admin:subscriptions_subscription_change", args=[subscription.pk])
    )

    assert response.status_code == 200
    assert _url(subscription) in response.content.decode()
    assert "Enviar alerta de teste" in response.content.decode()


def test_test_alert_form_is_prefilled_with_subscription_criteria():
    subscription = _subscription()
    client = Client()
    client.force_login(_staff_with_subscription_change_permission())

    response = client.get(_url(subscription))

    assert response.status_code == 200
    assert subscription.email in response.content.decode()
    assert response.context["form"].initial["ast"] == subscription.ast
    assert "Validar e enviar teste" in response.content.decode()


def test_matching_criteria_queue_a_test_without_creating_delivery():
    subscription = _subscription()
    proposition = _proposition()
    client = Client()
    client.force_login(_staff_with_subscription_change_permission())
    payload = {
        "proposition_id": proposition.pk,
        "ast": json.dumps(subscription.ast),
        "confirm_send": "on",
    }

    with patch("apps.subscriptions.admin.send_test_alert_email.delay") as delay:
        delay.return_value = SimpleNamespace(id="task-123")
        response = client.post(_url(subscription), payload)

    assert response.status_code == 302
    assert response.url == reverse(
        "admin:subscriptions_subscription_change", args=[subscription.pk]
    )
    delay.assert_called_once_with(subscription.pk, proposition.pk)
    assert not subscription.deliveries.exists()


def test_non_matching_criteria_do_not_queue_a_test():
    subscription = _subscription()
    proposition = _proposition()
    client = Client()
    client.force_login(_staff_with_subscription_change_permission())
    payload = {
        "proposition_id": proposition.pk,
        "ast": json.dumps({"field": "casa", "op": "eq", "value": "senado"}),
        "confirm_send": "on",
    }

    with patch("apps.subscriptions.admin.send_test_alert_email.delay") as delay:
        response = client.post(_url(subscription), payload)

    assert response.status_code == 200
    assert "nenhum e-mail foi enviado" in response.content.decode()
    delay.assert_not_called()


def test_inactive_subscription_cannot_receive_a_test_alert():
    subscription = _subscription(is_active=False)
    client = Client()
    client.force_login(_staff_with_subscription_change_permission())

    with patch("apps.subscriptions.admin.send_test_alert_email.delay") as delay:
        response = client.get(_url(subscription))

    assert response.status_code == 302
    assert response.url == reverse(
        "admin:subscriptions_subscription_change", args=[subscription.pk]
    )
    delay.assert_not_called()
