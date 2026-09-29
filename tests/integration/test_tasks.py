import datetime
from unittest.mock import patch

import pytest
from django.utils import timezone

from apps.subscriptions.tasks import (
    cleanup_unconfirmed_subscriptions,
    match_and_notify,
    send_alert_email,
    send_confirmation_email,
    send_test_alert_email,
)


def _make_proposition(**kwargs):
    from apps.propositions.models import Proposition

    defaults = dict(
        house="camara",
        external_id=1,
        type_code="pl",
        number_label="PL 1/2024",
        number=1,
        year=2024,
        presented_at=datetime.date(2024, 1, 1),
        ementa="Ementa de teste",
        current_status="Em tramitação",
    )
    defaults.update(kwargs)
    return Proposition.objects.create(**defaults)


def _make_subscription(**kwargs):
    from apps.subscriptions.models import Subscription

    defaults = dict(
        email="test@example.com",
        ast={},
        query="casa_camara",
        is_active=True,
    )
    defaults.update(kwargs)
    return Subscription.objects.create(**defaults)


@pytest.mark.django_db
class TestSendConfirmationEmail:
    def test_sends_and_returns_message_id(self, verified_sender):
        sub = _make_subscription(email="confirm@example.com", is_active=False)
        result = send_confirmation_email.delay(sub.pk)
        msg_id = result.get()
        assert msg_id and isinstance(msg_id, str)

    def test_skips_active_subscription(self, verified_sender):
        # task filters is_active=False; active sub → early return, no SES call
        sub = _make_subscription(email="active@example.com", is_active=True)
        result = send_confirmation_email.delay(sub.pk)
        assert result.get() is None

    def test_missing_id_is_noop(self):
        result = send_confirmation_email.delay(99999)
        assert result.get() is None


@pytest.mark.django_db
class TestSendAlertEmail:
    def test_sends_and_returns_message_id(self, verified_sender):
        sub = _make_subscription(email="alert@example.com", is_active=True)
        prop = _make_proposition(external_id=100)
        result = send_alert_email.delay(sub.pk, prop.pk)
        msg_id = result.get()
        assert msg_id and isinstance(msg_id, str)

    def test_skips_inactive_subscription(self, verified_sender):
        # task filters is_active=True; inactive sub → early return
        sub = _make_subscription(email="inactive@example.com", is_active=False)
        prop = _make_proposition(external_id=101)
        result = send_alert_email.delay(sub.pk, prop.pk)
        assert result.get() is None

    def test_missing_ids_are_noop(self, verified_sender):
        result = send_alert_email.delay(99999, 99998)
        assert result.get() is None


@pytest.mark.django_db
class TestSendTestAlertEmail:
    def test_sends_daily_template_without_creating_delivery(self):
        from apps.subscriptions.models import AlertDelivery

        sub = _make_subscription(email="test-alert@example.com", is_active=True)
        prop = _make_proposition(external_id=102)

        with patch("apps.subscriptions.tasks._send", return_value="test-message-id") as send:
            result = send_test_alert_email.delay(sub.pk, prop.pk)

        assert result.get() == "test-message-id"
        subject, _text, _html, recipient = send.call_args.args
        assert subject == "[TESTE] [Elas no Congresso] Nova proposição: PL 1/2024"
        assert recipient == sub.email
        assert not AlertDelivery.objects.filter(subscription=sub, proposition=prop).exists()

    def test_uses_weekly_template_for_weekly_subscription(self):
        from apps.subscriptions.models import Frequency

        sub = _make_subscription(
            email="weekly-test-alert@example.com", is_active=True, frequency=Frequency.WEEKLY
        )
        prop = _make_proposition(external_id=103)

        with patch("apps.subscriptions.tasks._send", return_value="test-message-id") as send:
            result = send_test_alert_email.delay(sub.pk, prop.pk)

        assert result.get() == "test-message-id"
        assert (
            send.call_args.args[0]
            == "[TESTE] [Elas no Congresso] Resumo da semana: 1 nova proposição"
        )


@pytest.mark.django_db
class TestMatchAndNotify:
    def test_matches_and_notifies(self, verified_sender):
        # token: casa_camara → subscription query must equal that token
        _make_subscription(email="match@example.com", query="casa_camara", is_active=True)
        prop = _make_proposition(external_id=200, house="camara")
        match_and_notify.delay(prop.pk)

    def test_no_match_no_email(self):
        # casa_senado won't match a camara proposition
        _make_subscription(email="nomatch@example.com", query="casa_senado", is_active=True)
        prop = _make_proposition(external_id=201, house="camara")
        match_and_notify.delay(prop.pk)

    def test_nonexistent_proposition_is_noop(self):
        match_and_notify.delay(99999)


@pytest.mark.django_db
class TestCleanupUnconfirmedSubscriptions:
    def test_deletes_expired(self):
        from apps.subscriptions.models import Subscription

        subs = [
            _make_subscription(email=f"expired{i}@example.com", is_active=False) for i in range(3)
        ]
        old_time = timezone.now() - datetime.timedelta(hours=49)
        ids = [s.pk for s in subs]
        Subscription.objects.filter(pk__in=ids).update(created_at=old_time)

        cleanup_unconfirmed_subscriptions.delay()

        assert Subscription.objects.filter(pk__in=ids).count() == 0

    def test_keeps_recent(self):
        from apps.subscriptions.models import Subscription

        sub = _make_subscription(email="recent@example.com", is_active=False)
        cleanup_unconfirmed_subscriptions.delay()

        assert Subscription.objects.filter(pk=sub.pk).exists()

    def test_keeps_active(self):
        from apps.subscriptions.models import Subscription

        sub = _make_subscription(email="keepactive@example.com", is_active=True)
        old_time = timezone.now() - datetime.timedelta(hours=49)
        Subscription.objects.filter(pk=sub.pk).update(created_at=old_time)

        cleanup_unconfirmed_subscriptions.delay()

        assert Subscription.objects.filter(pk=sub.pk).exists()
