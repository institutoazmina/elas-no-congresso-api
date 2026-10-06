import logging
from datetime import datetime, time

from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from apps.ingestion.models import IngestionRun
from apps.propositions.models import Proposition

from .collection import refresh_batch
from .models import WeeklyReport
from .report import REPORT_TZ, reporting_week
from .service import deliver_report, freeze_report, get_report, publication_url

logger = logging.getLogger(__name__)


def current_report():
    start, end = reporting_week(timezone.now().astimezone(REPORT_TZ).date())
    return WeeklyReport.objects.filter(publication_url=publication_url(), week_start=start).first()


@shared_task
def prepare_weekly_report():
    if not settings.WEEKLY_NEWSLETTER_ENABLED:
        return None
    start, end = reporting_week(timezone.now().astimezone(REPORT_TZ).date())
    report = get_report(start, end)
    with transaction.atomic():
        report = WeeklyReport.objects.select_for_update().get(pk=report.pk)
        if report.status != WeeklyReport.Status.COLLECTING:
            return report.pk
        if not report.collection:
            report.collection = {
                "targets": list(Proposition.objects.order_by("pk").values_list("pk", flat=True)),
                "results": {},
                "discovery": {},
            }
            report.save(update_fields=["collection", "updated_at"])
    refresh_weekly_batch.delay(report.pk)
    return report.pk


@shared_task
def refresh_weekly_batch(report_id):
    if not settings.WEEKLY_NEWSLETTER_ENABLED:
        return
    key = f"newsletter:refresh:{report_id}"
    if not cache.add(key, True, timeout=1800):
        return
    try:
        report = WeeklyReport.objects.get(pk=report_id)
        if report.status != WeeklyReport.Status.COLLECTING:
            return
        cutoff = datetime.combine(report.week_end, time(6, 45), REPORT_TZ)
        if timezone.now() >= cutoff:
            return
        pending = [
            pk
            for pk in report.collection.get("targets", [])
            if str(pk) not in report.collection.get("results", {})
        ]
        ids = pending[: settings.WEEKLY_NEWSLETTER_BATCH_SIZE]
        if not ids:
            return
        results = refresh_batch(ids)
        with transaction.atomic():
            report = WeeklyReport.objects.select_for_update().get(pk=report_id)
            if report.status != WeeklyReport.Status.COLLECTING:
                return
            # Deleted propositions must not keep the cursor stuck forever.
            report.collection["results"].update(
                {str(pk): results.get(str(pk), "deleted") for pk in ids}
            )
            report.save(update_fields=["collection", "updated_at"])
    finally:
        cache.delete(key)
    if len(pending) > len(ids):
        refresh_weekly_batch.apply_async(args=[report_id], countdown=5)


@shared_task
def finish_weekly_collection():
    if not settings.WEEKLY_NEWSLETTER_ENABLED:
        return
    report = current_report()
    if not report or report.status != WeeklyReport.Status.COLLECTING:
        return
    with transaction.atomic():
        report = WeeklyReport.objects.select_for_update().get(pk=report.pk)
        if report.status != WeeklyReport.Status.COLLECTING:
            return
        targets = set(report.collection.get("targets", []))
        targets.update(Proposition.objects.values_list("pk", flat=True))
        report.collection["targets"] = sorted(targets)
        morning = datetime.combine(report.week_end, time(6), REPORT_TZ)
        report.collection["discovery"] = {}
        for house in ("camara", "senado"):
            run = (
                IngestionRun.objects.filter(house=house, started_at__gte=morning)
                .order_by("-started_at")
                .first()
            )
            report.collection["discovery"][house] = {
                "run_id": run.pk if run else None,
                "ok": bool(
                    run and run.status == IngestionRun.Status.SUCCESS and run.error_count == 0
                ),
            }
        report.save(update_fields=["collection", "updated_at"])
    refresh_weekly_batch.delay(report.pk)
    if timezone.now() < datetime.combine(report.week_end, time(6, 44), REPORT_TZ):
        finish_weekly_collection.apply_async(countdown=60)


@shared_task(bind=True, max_retries=2, default_retry_delay=120)
def deliver_weekly_report(self, report_id=None, manual=False):
    if not settings.WEEKLY_NEWSLETTER_ENABLED and not manual:
        return
    report = current_report() if report_id is None else WeeklyReport.objects.get(pk=report_id)
    if not report:
        logger.error("Weekly newsletter missing preparation; exporting available data")
        start, end = reporting_week(timezone.now().astimezone(REPORT_TZ).date())
        report = get_report(start, end)
    if report.status == WeeklyReport.Status.COLLECTING:
        collection = report.collection
        complete = (
            all(
                collection.get("discovery", {}).get(house, {}).get("ok")
                for house in ("camara", "senado")
            )
            and all(
                collection.get("results", {}).get(str(pk)) == "ok"
                for pk in collection.get("targets", [])
            )
            and set(Proposition.objects.values_list("pk", flat=True)).issubset(
                collection.get("targets", [])
            )
        )
        report = freeze_report(report.pk, complete)
        if not complete:
            logger.warning("Weekly report %s has incomplete collection", report.pk)
    result = deliver_report(report.pk)
    if result.status == WeeklyReport.Status.FAILED and self.request.retries < self.max_retries:
        raise self.retry(args=[report.pk], kwargs={"manual": manual})
    return {"id": result.pk, "status": result.status}


@shared_task
def check_weekly_deadline():
    if not settings.WEEKLY_NEWSLETTER_ENABLED:
        return
    report = current_report()
    if not report or report.status != WeeklyReport.Status.DELIVERED:
        if report:
            WeeklyReport.objects.filter(pk=report.pk).update(deadline_missed=True)
        logger.error("Weekly newsletter not delivered by Monday 07:00")
