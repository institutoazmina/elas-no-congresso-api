import logging
from datetime import datetime, time, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import WeeklyReport
from .report import REPORT_TZ, build_snapshot, render
from .substack import AuthenticationRequiredError, DraftOnlyClient

logger = logging.getLogger(__name__)


def publication_url():
    return settings.SUBSTACK_PUBLICATION_URL.rstrip("/").lower()


def get_report(start, end):
    report = WeeklyReport.objects.get_or_create(
        publication_url=publication_url(),
        week_start=start,
        defaults={
            "week_end": end,
            "title": f"Elas no Congresso — Radar {start:%d/%m/%Y} a {end - timedelta(days=1):%d/%m/%Y}",
        },
    )[0]
    if report.week_end != end:
        raise ValueError(
            f"Relatório {report.pk} já usa este início com outra data final; "
            "usar --report-id para consultar/entregar o período original."
        )
    return report


def freeze_report(report_id, complete):
    with transaction.atomic():
        report = WeeklyReport.objects.select_for_update().get(pk=report_id)
        if report.status != WeeklyReport.Status.COLLECTING:
            return report
        report.snapshot = build_snapshot(report.week_start, report.week_end)
        report.is_complete = complete
        report.markdown, report.html = render(report.snapshot, complete)
        report.status = WeeklyReport.Status.READY
        report.save()
        return report


def deliver_report(report_id, client_factory=DraftOnlyClient):
    """Durably reserve a write; an uncertain outcome never permits blind replay."""
    with transaction.atomic():
        report = WeeklyReport.objects.select_for_update().get(pk=report_id)
        if report.status in {WeeklyReport.Status.COLLECTING, WeeklyReport.Status.DELIVERED}:
            return report
        if report.status == WeeklyReport.Status.DELIVERING:
            if report.attempt_started_at and timezone.now() - report.attempt_started_at < timedelta(
                minutes=10
            ):
                return report
            # A killed worker may have reached Substack before saving the ID.
            report.status = WeeklyReport.Status.UNCERTAIN
        uncertain = report.status == WeeklyReport.Status.UNCERTAIN
        report.status = WeeklyReport.Status.DELIVERING
        report.attempt_started_at = timezone.now()
        report.save(update_fields=["status", "attempt_started_at", "updated_at"])
    client = None
    write_started = False
    try:
        client = client_factory(report.publication_url)
        draft_id = report.draft_id or client.find(report.title)
        if not draft_id:
            if uncertain:
                raise ValueError(
                    "Entrega incerta: localizar rascunho manualmente; nenhuma nova criação executada."
                )
            write_started = True
            draft_id = client.create(report.title, report.markdown)
        # Save the ID before verification so read failures cannot trigger a create.
        report.draft_id = draft_id
        report.draft_url = f"{report.publication_url}/publish/post/{draft_id}"
        report.save(update_fields=["draft_id", "draft_url", "updated_at"])
        client.verify(draft_id)
        report.status = WeeklyReport.Status.DELIVERED
        report.delivered_at = timezone.now()
        # O prazo de segunda às 07:00 só existe para a semana padrão do Beat.
        standard_week = (
            report.week_start.weekday() == 0
            and (report.week_end - report.week_start).days == 7
        )
        report.deadline_missed = standard_week and report.delivered_at >= datetime.combine(
            report.week_end, time(7), REPORT_TZ
        )
        report.error = ""
    except AuthenticationRequiredError:
        report.status = (
            WeeklyReport.Status.UNCERTAIN if uncertain else WeeklyReport.Status.AUTH_REQUIRED
        )
        report.error = "Renovar sessão Substack e verificar acesso à publicação."
    except Exception as exc:
        report.status = (
            WeeklyReport.Status.UNCERTAIN
            if uncertain or write_started or report.draft_id
            else WeeklyReport.Status.FAILED
        )
        report.error = f"{type(exc).__name__}: falha na entrega; exportação preservada."
        logger.warning("Weekly report %s delivery failed (%s)", report.pk, type(exc).__name__)
    finally:
        if client:
            client.close()
    report.save(update_fields=["status", "error", "delivered_at", "deadline_missed", "updated_at"])
    return report
