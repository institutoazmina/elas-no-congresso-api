import logging

from celery import shared_task
from django.conf import settings
from django.utils import timezone

from .freshness import coverage_complete, source_coverage
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
    return get_report(start, end).pk


@shared_task
def refresh_weekly_batch(report_id):
    # Compatibility with messages already in the broker at deployment.
    logger.info(
        "Retired newsletter refresh for report %s; daily ingestion owns freshness", report_id
    )


@shared_task
def finish_weekly_collection():
    if not settings.WEEKLY_NEWSLETTER_ENABLED:
        return
    report = current_report()
    if report and report.status == WeeklyReport.Status.COLLECTING:
        coverage = source_coverage(report.week_start, report.week_end)
        report.collection = coverage
        report.save(update_fields=["collection", "updated_at"])
        if coverage_complete(coverage):
            freeze_report(report.pk, True)


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
        report.collection = source_coverage(report.week_start, report.week_end)
        report.save(update_fields=["collection", "updated_at"])
        report = freeze_report(report.pk, coverage_complete(report.collection))
    if not report.is_complete:
        logger.error(
            "Weekly report %s blocked: incomplete daily source coverage; export preserved",
            report.pk,
        )
        return {"id": report.pk, "status": report.status, "blocked": True}
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
