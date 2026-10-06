"""Source coverage is independent of asynchronous OCR and AI completion."""

from datetime import datetime, time, timedelta

from django.db.models import Q
from django.utils import timezone

from apps.ingestion.models import IngestionCheckpoint, IngestionRun
from apps.propositions.models import Proposition

from .report import REPORT_TZ


def source_coverage(start, end):
    now = timezone.now()
    midnight = datetime.combine(end, time(), REPORT_TZ)
    # An open period is explicitly through the latest completed daily ingestion.
    required = min(midnight, now - timedelta(hours=26)) if midnight > now else midnight
    sources = {}
    for house in ("camara", "senado"):
        checkpoint = IngestionCheckpoint.objects.filter(house=house).first()
        latest = (
            IngestionRun.objects.filter(house=house, kind="daily").order_by("-started_at").first()
        )
        reasons = []
        if not checkpoint or not checkpoint.baseline_complete:
            reasons.append("baseline_pending")
        if not checkpoint or not checkpoint.covered_since or checkpoint.covered_since > start:
            reasons.append("period_not_covered")
        covered = checkpoint.covered_until if checkpoint else None
        if not covered or covered < required or covered < now - timedelta(hours=26):
            reasons.append("source_stale")
        if not latest or latest.status != IngestionRun.Status.SUCCESS or latest.error_count:
            reasons.append("daily_run_incomplete")
        if (
            Proposition.objects.filter(house=house)
            .filter(Q(reconciled_at__isnull=True) | Q(reconciled_at__lt=now - timedelta(days=8)))
            .exists()
        ):
            reasons.append("reconciliation_stale")
        sources[house] = {
            "ok": not reasons,
            "run_id": latest.pk if latest else None,
            "covered_until": covered.isoformat() if covered else None,
            "reasons": reasons,
        }
    return {"mode": "database", "discovery": sources, "as_of": now.isoformat()}


def coverage_complete(coverage):
    return all(coverage["discovery"][house]["ok"] for house in ("camara", "senado"))
