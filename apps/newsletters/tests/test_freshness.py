from datetime import date, timedelta
from io import StringIO
from unittest.mock import Mock

import pytest
from django.core.management import CommandError, call_command
from django.utils import timezone

from apps.ingestion.models import IngestionCheckpoint, IngestionRun
from apps.newsletters.freshness import coverage_complete, source_coverage
from apps.newsletters.models import WeeklyReport
from apps.newsletters.substack import AuthenticationRequiredError

pytestmark = pytest.mark.django_db


def checkpoints():
    for house in ("camara", "senado"):
        run = IngestionRun.objects.create(
            house=house,
            window_start=date(2026, 9, 1),
            window_end=timezone.localdate(),
            status="success",
        )
        IngestionCheckpoint.objects.create(
            house=house,
            covered_since=date(2026, 9, 1),
            covered_until=timezone.now(),
            baseline_complete=True,
            active_run=run,
        )


def test_fresh_database_report_uses_no_source_or_ai_calls(monkeypatch):
    checkpoints()
    forbidden = Mock(side_effect=AssertionError("Unexpected external collection/AI"))
    monkeypatch.setattr(
        "apps.newsletters.management.commands.weekly_newsletter.refresh_batch", forbidden
    )
    monkeypatch.setattr("apps.propositions.quiteria.get_classifier", forbidden)
    call_command(
        "weekly_newsletter",
        start_date=date(2026, 9, 29),
        end_date=date(2026, 10, 5),
        stdout=StringIO(),
    )
    report = WeeklyReport.objects.get()
    assert report.is_complete and report.collection["mode"] == "database"
    forbidden.assert_not_called()


def test_stale_or_missing_baseline_blocks_delivery_but_explicit_override_is_allowed(monkeypatch):
    checkpoints()
    IngestionCheckpoint.objects.filter(house="senado").update(
        baseline_complete=False, covered_until=timezone.now() - timedelta(days=2)
    )
    delivery = Mock(
        return_value=Mock(
            status=WeeklyReport.Status.DELIVERED,
            pk=1,
            draft_url="url",
            snapshot=[],
            is_complete=False,
            collection={},
            get_status_display=lambda: "Entregue",
        )
    )
    monkeypatch.setattr(
        "apps.newsletters.management.commands.weekly_newsletter.deliver_report", delivery
    )
    args = {
        "start_date": date(2026, 9, 29),
        "end_date": date(2026, 10, 5),
        "deliver": True,
        "stdout": StringIO(),
    }
    with pytest.raises(CommandError, match="cobertura diária incompleta"):
        call_command("weekly_newsletter", **args)
    delivery.assert_not_called()
    report = WeeklyReport.objects.get()
    assert "Coleta incompleta" in report.markdown
    call_command("weekly_newsletter", **args, allow_incomplete=True)
    delivery.assert_called_once()


def test_incomplete_current_run_blocks_even_with_previous_recent_watermark():
    checkpoints()
    IngestionRun.objects.create(
        house="camara",
        window_start=date(2026, 10, 5),
        window_end=date(2026, 10, 7),
        status="failed",
        error_count=1,
    )
    coverage = source_coverage(date(2026, 9, 29), date(2026, 10, 7))
    assert not coverage_complete(coverage)
    assert "daily_run_incomplete" in coverage["discovery"]["camara"]["reasons"]


def test_auth_preflight_fails_without_collection_or_report_writes(monkeypatch):
    client = Mock()
    client.check_access.side_effect = AuthenticationRequiredError("session expired")
    monkeypatch.setattr(
        "apps.newsletters.management.commands.weekly_newsletter.DraftOnlyClient",
        Mock(return_value=client),
    )
    with pytest.raises(CommandError, match="renovar sessão"):
        call_command("weekly_newsletter", check_auth=True, stdout=StringIO())
    assert not WeeklyReport.objects.exists()
    client.close.assert_called_once()
