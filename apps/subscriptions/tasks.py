import logging

from anymail.exceptions import AnymailError
from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone

logger = logging.getLogger(__name__)


def _send(subject: str, body_text: str, body_html: str, to: str) -> str:
    """Send a multipart email via the configured backend; return the message id."""
    msg = EmailMultiAlternatives(subject=subject, body=body_text, to=[to])
    msg.attach_alternative(body_html, "text/html")
    msg.send()
    return msg.anymail_status.message_id


@shared_task(bind=True, autoretry_for=(AnymailError,), retry_backoff=True, max_retries=5)
def send_alert_email(self, subscription_id: int, proposition_id: int):
    from apps.propositions.models import Proposition
    from apps.subscriptions.models import Subscription

    try:
        sub = Subscription.objects.get(pk=subscription_id, is_active=True)
        prop = Proposition.objects.get(pk=proposition_id)
    except (Subscription.DoesNotExist, Proposition.DoesNotExist):
        return

    base_url = settings.SITE_BASE_URL.rstrip("/")
    unsubscribe_url = f"{base_url}/api/v1/subscriptions/unsubscribe/{sub.unsubscribe_token}"
    prop_url = f"{base_url}/api/v1/propositions/{prop.pk}"

    subject = f"[Elas no Congresso] Nova proposição: {prop.number_label}"
    body_text = (
        f"Proposição: {prop.number_label} ({prop.year})\n"
        f"Casa: {prop.house}\n"
        f"Ementa: {prop.ementa[:500]}\n\n"
        f"Ver detalhes: {prop_url}\n\n"
        f"Cancelar inscrição: {unsubscribe_url}"
    )
    body_html = (
        f"<h2>{prop.number_label} ({prop.year})</h2>"
        f"<p><strong>Casa:</strong> {prop.house}</p>"
        f"<p><strong>Ementa:</strong> {prop.ementa[:500]}</p>"
        f"<p><a href='{prop_url}'>Ver detalhes</a></p>"
        f"<hr><p><small><a href='{unsubscribe_url}'>Cancelar inscrição</a></small></p>"
    )

    message_id = _send(subject, body_text, body_html, sub.email)
    logger.info("Alert sent to %s for proposition %d", sub.email, proposition_id)
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

    subject = "[Elas no Congresso] Confirme sua inscricao de alertas"
    body_text = (
        f"Clique no link abaixo para confirmar sua inscricao:\n\n{confirm_url}\n\n"
        "O link expira em 48 horas."
    )
    body_html = (
        f"<p>Clique no link abaixo para confirmar sua inscricao:</p>"
        f"<p><a href='{confirm_url}'>{confirm_url}</a></p>"
        "<p>O link expira em 48 horas.</p>"
    )

    message_id = _send(subject, body_text, body_html, sub.email)
    logger.info("Confirmation sent to %s", sub.email)
    return message_id


@shared_task
def match_and_notify(proposition_id: int):
    from .service import match_proposition

    matched_ids = match_proposition(proposition_id)
    for sub_id in matched_ids:
        send_alert_email.delay(sub_id, proposition_id)
    logger.info("Proposition %d matched %d subscriptions", proposition_id, len(matched_ids))


@shared_task
def cleanup_unconfirmed_subscriptions():
    from datetime import timedelta

    from apps.subscriptions.models import Subscription

    cutoff = timezone.now() - timedelta(hours=settings.SUBSCRIPTION_CONFIRM_TTL_HOURS)
    deleted, _ = Subscription.objects.filter(is_active=False, created_at__lt=cutoff).delete()
    logger.info("Cleaned up %d unconfirmed subscriptions", deleted)
