import logging

from anymail.exceptions import AnymailError
from celery import shared_task
from django.conf import settings
from django.core.mail import EmailMultiAlternatives
from django.utils import timezone

from .email_templates import render_confirmation_email, render_daily_alert, render_weekly_digest

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


@shared_task(bind=True, autoretry_for=(AnymailError,), retry_backoff=True, max_retries=5)
def send_alert_email(self, subscription_id: int, proposition_id: int):
    from apps.propositions.models import Proposition
    from apps.subscriptions.models import AlertDelivery, Subscription

    try:
        sub = Subscription.objects.get(pk=subscription_id, is_active=True)
        prop = Proposition.objects.get(pk=proposition_id)
    except (Subscription.DoesNotExist, Proposition.DoesNotExist):
        return

    # O match roda de novo quando a anotação humana chega: o unique é o que
    # impede a mesma proposição de virar dois e-mails.
    _, primeira_vez = AlertDelivery.objects.get_or_create(subscription=sub, proposition=prop)
    if not primeira_vez:
        return

    base_url = settings.SITE_BASE_URL.rstrip("/")
    unsubscribe_url = f"{base_url}/api/v1/subscriptions/unsubscribe/{sub.unsubscribe_token}"
    prop_url = f"{base_url}/api/v1/propositions/{prop.pk}"

    pl_identifier = prop.number_label.removeprefix("PL ")
    subject = f"O PL {pl_identifier} que vc acompanha tem novidade"
    body_text = (
        f"Proposição: {prop.number_label} ({prop.year})\n"
        f"Casa: {prop.house}\n"
        f"Ementa: {prop.ementa[:500]}\n\n"
        f"Ver detalhes: {prop_url}\n\n"
        f"Cancelar inscrição: {unsubscribe_url}"
    )
    body_html = render_daily_alert(sub, prop)

    message_id = _send(subject, body_text, body_html, sub.email)
    logger.info("Alert sent to %s for proposition %d", sub.email, proposition_id)
    return message_id


@shared_task(bind=True, autoretry_for=(AnymailError,), retry_backoff=True, max_retries=5)
def send_test_alert_email(self, subscription_id: int, proposition_id: int):
    """Envia a renderização real sem registrar uma entrega de produção.

    Esta tarefa só é acionada pela ferramenta restrita do Django Admin. Ela
    permite repetir o teste para a mesma proposição sem afetar `AlertDelivery`
    nem o histórico de notificações.
    """
    from apps.propositions.models import Proposition
    from apps.subscriptions.models import Frequency, Subscription

    try:
        sub = Subscription.objects.get(pk=subscription_id, is_active=True)
        prop = Proposition.objects.get(pk=proposition_id)
    except (Subscription.DoesNotExist, Proposition.DoesNotExist):
        return

    if sub.frequency == Frequency.WEEKLY:
        subject = "[TESTE] [Elas no Congresso] Resumo da semana: 1 nova proposição"
        body_text = (
            "E-mail de teste do resumo semanal.\n\n"
            f"- {prop.number_label} ({prop.house}): {prop.ementa[:200]}"
        )
        body_html = render_weekly_digest(sub, [prop])
    else:
        subject = f"[TESTE] [Elas no Congresso] Nova proposição: {prop.number_label}"
        body_text = (
            "E-mail de teste do alerta diário.\n\n"
            f"Proposição: {prop.number_label} ({prop.year})\n"
            f"Casa: {prop.house}\n"
            f"Ementa: {prop.ementa[:500]}"
        )
        body_html = render_daily_alert(sub, prop)

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
    """Só a fila diária dispara e-mail na hora; a semanal espera o digest."""
    from .models import Frequency
    from .service import match_proposition

    matched_ids = match_proposition(proposition_id, frequency=Frequency.DAILY)
    for sub_id in matched_ids:
        send_alert_email.delay(sub_id, proposition_id)
    logger.info("Proposition %d matched %d daily subscriptions", proposition_id, len(matched_ids))


@shared_task
def send_weekly_digest():
    """Um e-mail por inscrição semanal com o que entrou na semana.

    Re-casa as proposições recentes em vez de guardar uma fila de pendências:
    o volume semanal é pequeno e assim não há estado para desincronizar.
    # ponytail: janela fixa de 7 dias. Se o beat atrasar ou rodar duas vezes,
    # repete/perde itens — trocar por marca d'água (last_digest_at) se doer.
    """
    from datetime import timedelta

    from apps.propositions.models import Proposition

    from .models import Frequency, Subscription
    from .service import match_proposition

    cutoff = timezone.now() - timedelta(days=7)
    recent = list(
        Proposition.objects.filter(
            created_at__gte=cutoff,
        ).order_by("presented_at", "pk")
    )
    if not recent:
        logger.info("Weekly digest: nothing new this week")
        return

    per_subscription: dict[int, list] = {}
    for prop in recent:
        for sub_id in match_proposition(prop.pk, frequency=Frequency.WEEKLY):
            per_subscription.setdefault(sub_id, []).append(prop)

    for sub in Subscription.objects.filter(pk__in=per_subscription):
        send_digest_email.delay(sub.pk, [p.pk for p in per_subscription[sub.pk]])
    logger.info("Weekly digest queued for %d subscriptions", len(per_subscription))


@shared_task(bind=True, autoretry_for=(AnymailError,), retry_backoff=True, max_retries=5)
def send_digest_email(self, subscription_id: int, proposition_ids: list[int]):
    from apps.propositions.models import Proposition
    from apps.subscriptions.models import Subscription

    try:
        sub = Subscription.objects.get(pk=subscription_id, is_active=True)
    except Subscription.DoesNotExist:
        return

    props = list(Proposition.objects.filter(pk__in=proposition_ids).order_by("presented_at", "pk"))
    if not props:
        return

    base_url = settings.SITE_BASE_URL.rstrip("/")
    unsubscribe_url = f"{base_url}/api/v1/subscriptions/unsubscribe/{sub.unsubscribe_token}"

    subject = f"[Elas no Congresso] Resumo da semana: {len(props)} novas proposições"
    lines = [
        f"- {p.number_label} ({p.house}): {p.ementa[:200]}\n  {base_url}/api/v1/propositions/{p.pk}"
        for p in props
    ]
    body_text = "\n\n".join(
        ["O que entrou no Congresso esta semana:", *lines, f"Cancelar inscrição: {unsubscribe_url}"]
    )
    body_html = render_weekly_digest(sub, props)

    message_id = _send(subject, body_text, body_html, sub.email)
    logger.info("Weekly digest sent to %s with %d propositions", sub.email, len(props))
    return message_id


@shared_task
def cleanup_unconfirmed_subscriptions():
    from datetime import timedelta

    from apps.subscriptions.models import Subscription

    cutoff = timezone.now() - timedelta(hours=settings.SUBSCRIPTION_CONFIRM_TTL_HOURS)
    deleted, _ = Subscription.objects.filter(is_active=False, created_at__lt=cutoff).delete()
    logger.info("Cleaned up %d unconfirmed subscriptions", deleted)
