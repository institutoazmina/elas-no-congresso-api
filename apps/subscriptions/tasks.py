import logging
from datetime import date, datetime

from anymail.exceptions import AnymailError
from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.utils import timezone

from .email_templates import (
    render_confirmation_email,
    render_daily_digest,
    render_daily_digest_text,
)

logger = logging.getLogger(__name__)


def _send(subject: str, body_text: str, body_html: str, to: str) -> str | None:
    """Send a multipart email via the configured backend; return the message id.

    Returns None when the active backend isn't anymail (e.g. locmem/console),
    so the task doesn't crash outside production.
    """
    msg = EmailMultiAlternatives(subject=subject, body=body_text, to=[to])
    msg.attach_alternative(body_html, "text/html")
    msg.send()
    status = getattr(msg, "anymail_status", None)
    return status.message_id if status else None


@shared_task
def send_alert_email(subscription_id: int, proposition_id: int):
    """Compatibility for already queued tasks: collect the match, never send immediately."""
    from apps.propositions.models import Proposition
    from apps.subscriptions.models import AlertDelivery, Frequency, PendingAlert, Subscription

    if (
        not Subscription.objects.filter(
            pk=subscription_id, is_active=True, frequency=Frequency.DAILY
        ).exists()
        or not Proposition.objects.filter(pk=proposition_id, is_approved=True).exists()
    ):
        return
    # Histórico por endereço, igual ao resumo: várias inscrições recebem uma vez.
    if AlertDelivery.objects.filter(
        subscription__email=Subscription.objects.filter(pk=subscription_id).values("email")[:1],
        proposition_id=proposition_id,
    ).exists():
        return
    PendingAlert.objects.get_or_create(
        subscription_id=subscription_id, proposition_id=proposition_id
    )


def _daily_cutoff(now):
    local_now = timezone.localtime(now)
    return timezone.make_aware(
        datetime.combine(local_now.date(), settings.DAILY_DIGEST_TIME),
        timezone.get_current_timezone(),
    )


@shared_task
def send_daily_digest():
    """Queue one digest per address using a fixed local-time cutoff."""
    from .models import Frequency, PendingAlert

    now = timezone.now()
    cutoff = _daily_cutoff(now)
    if now < cutoff:
        return
    emails = (
        PendingAlert.objects.filter(
            subscription__is_active=True,
            subscription__frequency=Frequency.DAILY,
            proposition__is_approved=True,
            created_at__lte=cutoff,
        )
        .order_by("subscription__email")
        .values_list("subscription__email", flat=True)
        .distinct()
    )
    for email in emails:
        send_daily_digest_email.delay(email, cutoff.date().isoformat())


@shared_task(bind=True, autoretry_for=(AnymailError,), retry_backoff=True, max_retries=5)
def send_daily_digest_email(self, email: str, delivery_date: str):
    from apps.propositions.models import Proposition

    from .models import AlertDelivery, DailyDigestDelivery, Frequency, PendingAlert, Subscription
    from .service import match_proposition

    now = timezone.now()
    cutoff = _daily_cutoff(now)
    # Stale tasks leave their pending items for today's scheduled digest.
    if now < cutoff or date.fromisoformat(delivery_date) != cutoff.date():
        return

    with transaction.atomic():
        delivery, _ = DailyDigestDelivery.objects.get_or_create(
            email=email, delivery_date=cutoff.date()
        )
        # Serialize concurrent/repeated tasks for the same address and day.
        delivery = DailyDigestDelivery.objects.select_for_update().get(pk=delivery.pk)
        if delivery.sent_at:
            return delivery.message_id

        subscriptions = list(
            Subscription.objects.filter(
                email=email, is_active=True, frequency=Frequency.DAILY
            ).order_by("pk")
        )
        if not subscriptions:
            return
        pending = list(
            PendingAlert.objects.select_for_update()
            .filter(subscription__in=subscriptions, created_at__lte=cutoff)
            .order_by("pk")
        )
        props = list(
            Proposition.objects.filter(
                pk__in={item.proposition_id for item in pending}, is_approved=True
            )
            .select_related("analysis")
            .prefetch_related(
                "annotations",
                "events",
                "authors__parliamentarian",
                "authors__institutional_author",
                "authors__party",
                "rapporteurs__parliamentarian",
                "rapporteurs__party",
            )
            .order_by("presented_at", "pk")
        )
        # Revalidate eligibility: an annotation/filter/approval can change while queued.
        matches = {prop.pk: set(match_proposition(prop.pk, Frequency.DAILY)) for prop in props}
        eligible = [
            item
            for item in pending
            if item.subscription_id in matches.get(item.proposition_id, set())
        ]
        delivered_ids = set(
            AlertDelivery.objects.filter(subscription__email=email).values_list(
                "proposition_id", flat=True
            )
        )
        proposition_ids = {item.proposition_id for item in eligible} - delivered_ids
        props = [prop for prop in props if prop.pk in proposition_ids]
        if not props:
            PendingAlert.objects.filter(pk__in=[item.pk for item in pending]).delete()
            return

        noun = "proposição" if len(props) == 1 else "proposições"
        subject = f"[Elas no Congresso] Resumo do dia: {len(props)} {noun}"
        body_text = render_daily_digest_text(subscriptions[0], props)
        body_html = render_daily_digest(subscriptions[0], props)
        message_id = _send(subject, body_text, body_html, email)

        # Only record success/remove pending matches after the email backend succeeds.
        # Sending and committing are not atomic across SES and PostgreSQL: a worker
        # crash after SES accepts the email but before commit can cause a redelivery.
        AlertDelivery.objects.bulk_create(
            [
                AlertDelivery(
                    subscription_id=item.subscription_id, proposition_id=item.proposition_id
                )
                for item in eligible
                if item.proposition_id in proposition_ids
            ],
            ignore_conflicts=True,
        )
        PendingAlert.objects.filter(pk__in=[item.pk for item in pending]).delete()
        delivery.sent_at = timezone.now()
        delivery.message_id = message_id
        delivery.save(update_fields=["sent_at", "message_id"])
    logger.info("Daily digest sent to %s with %d propositions", email, len(props))
    return message_id


@shared_task(bind=True, autoretry_for=(AnymailError,), retry_backoff=True, max_retries=5)
def send_test_alert_email(self, subscription_id: int, proposition_id: int):
    """Envia a renderização real sem registrar uma entrega de produção.

    Esta tarefa só é acionada pela ferramenta restrita do Django Admin. Ela
    permite repetir o teste para a mesma proposição sem afetar `AlertDelivery`
    nem o histórico de notificações.
    """
    from apps.propositions.models import Proposition
    from apps.subscriptions.models import Subscription

    try:
        sub = Subscription.objects.get(pk=subscription_id, is_active=True)
        prop = Proposition.objects.get(pk=proposition_id)
    except (Subscription.DoesNotExist, Proposition.DoesNotExist):
        return

    subject = "[TESTE] [Elas no Congresso] Resumo do dia: 1 proposição"
    body_text = render_daily_digest_text(sub, [prop])
    body_html = render_daily_digest(sub, [prop])

    message_id = _send(subject, body_text, body_html, sub.email)
    logger.info("Test alert sent to %s for proposition %d", sub.email, proposition_id)
    return message_id


@shared_task(bind=True, autoretry_for=(AnymailError,), retry_backoff=True, max_retries=5)
def send_confirmation_email(self, subscription_id: int):
    from apps.subscriptions.models import Subscription

    try:
        sub = Subscription.objects.get(pk=subscription_id, is_active=False)
    except Subscription.DoesNotExist:
        return

    base_url = settings.SITE_BASE_URL.rstrip("/")
    confirm_url = f"{base_url}/api/v1/subscriptions/confirm/{sub.confirm_token}"

    subject = "Confirme sua inscrição em nossos alertas"
    body_text = (
        f"Clique no link abaixo para confirmar sua inscricao:\n\n{confirm_url}\n\n"
        "O link expira em 48 horas."
    )
    body_html = render_confirmation_email(sub)

    message_id = _send(subject, body_text, body_html, sub.email)
    logger.info("Confirmation sent to %s", sub.email)
    return message_id


@shared_task
def match_and_notify(proposition_id: int):
    """Persist daily matches; delivery waits for the scheduled digest."""
    from apps.propositions.models import Proposition

    from .models import Frequency
    from .service import match_proposition

    if not Proposition.objects.filter(pk=proposition_id, is_approved=True).exists():
        logger.info("Proposition %d is not approved; daily alert skipped", proposition_id)
        return

    matched_ids = match_proposition(proposition_id, frequency=Frequency.DAILY)
    for sub_id in matched_ids:
        send_alert_email(sub_id, proposition_id)
    logger.info("Proposition %d matched %d daily subscriptions", proposition_id, len(matched_ids))


@shared_task
def send_weekly_digest():
    """Discard legacy scheduled/queued weekly tasks after retiring the template."""
    logger.info("Weekly digest retired; legacy task skipped")


@shared_task
def send_digest_email(subscription_id: int, proposition_ids: list[int]):
    """Discard weekly sends already present in the broker during deployment."""
    logger.info("Weekly digest retired; legacy send skipped for subscription %d", subscription_id)


@shared_task
def cleanup_unconfirmed_subscriptions():
    from datetime import timedelta

    from apps.subscriptions.models import Subscription

    cutoff = timezone.now() - timedelta(hours=settings.SUBSCRIPTION_CONFIRM_TTL_HOURS)
    # Só pedidos nunca confirmados: inscrições canceladas guardam o histórico de
    # entregas e mantêm válido o link de cancelamento dos e-mails já enviados.
    deleted, _ = Subscription.objects.filter(
        is_active=False, confirmed_at__isnull=True, created_at__lt=cutoff
    ).delete()
    logger.info("Cleaned up %d unconfirmed subscriptions", deleted)
