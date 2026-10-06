from datetime import date, datetime
from io import StringIO
from unittest.mock import Mock

import pytest
from django.contrib.auth.models import Permission, User
from django.core.management import CommandError, call_command
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from apps.ingestion.models import IngestionCheckpoint, IngestionRun
from apps.newsletters import collection, tasks
from apps.newsletters.models import WeeklyReport
from apps.newsletters.report import REPORT_TZ
from apps.newsletters.service import freeze_report, get_report
from apps.propositions.models import Proposition


@pytest.fixture
def clock(monkeypatch, settings):
    settings.WEEKLY_NEWSLETTER_ENABLED = True
    monkeypatch.setattr(timezone, "now", lambda: datetime(2026, 10, 5, 4, tzinfo=REPORT_TZ))
    monkeypatch.setattr(tasks.refresh_weekly_batch, "delay", Mock())
    monkeypatch.setattr(tasks.refresh_weekly_batch, "apply_async", Mock())
    monkeypatch.setattr(tasks.finish_weekly_collection, "apply_async", Mock())


def prop(number=1, **extra):
    return Proposition.objects.create(
        house="camara",
        external_id=number,
        type_code="PL",
        number_label=f"PL {number}/2026",
        number=number,
        year=2026,
        presented_at=date(2026, 9, 30),
        ementa="Ementa oficial",
        **extra,
    )


def fresh_sources():
    Proposition.objects.update(reconciled_at=timezone.now())
    for house in ("camara", "senado"):
        run = IngestionRun.objects.create(
            house=house,
            window_start=date(2026, 9, 28),
            window_end=date(2026, 10, 6),
            status="success",
        )
        IngestionCheckpoint.objects.create(
            house=house,
            covered_since=date(2026, 9, 28),
            covered_until=timezone.now(),
            baseline_complete=True,
            active_run=run,
        )


@pytest.mark.django_db
def test_database_snapshot_includes_unapproved_and_morning_additions(clock, monkeypatch):
    first = prop(is_approved=False, is_active=False)
    report_id = tasks.prepare_weekly_report()
    assert tasks.prepare_weekly_report() == report_id
    second = prop(2)
    monkeypatch.setattr(timezone, "now", lambda: datetime(2026, 10, 5, 6, 36, tzinfo=REPORT_TZ))
    fresh_sources()
    # A source refresh must never be reached by newsletter jobs.
    monkeypatch.setattr(
        collection, "refresh_batch", Mock(side_effect=AssertionError("unexpected HTTP"))
    )
    tasks.finish_weekly_collection()
    report = WeeklyReport.objects.get(pk=report_id)
    assert report.is_complete
    assert all(item["ok"] for item in report.collection["discovery"].values())
    assert {entry["id"] for entry in report.snapshot} == {first.pk, second.pk}


@pytest.mark.django_db
def test_incomplete_coverage_blocks_delivery_and_preserves_export(clock, monkeypatch):
    prop()
    report_id = tasks.prepare_weekly_report()
    delivery = Mock()
    monkeypatch.setattr(tasks, "deliver_report", delivery)
    result = tasks.deliver_weekly_report(report_id)
    assert result["blocked"]
    delivery.assert_not_called()
    report = WeeklyReport.objects.get(pk=report_id)
    assert not report.is_complete
    assert "Coleta incompleta" in report.markdown
    tasks.check_weekly_deadline()
    report.refresh_from_db()
    assert report.deadline_missed


@pytest.mark.django_db
def test_daily_item_errors_prevent_complete_snapshot(clock):
    report_id = tasks.prepare_weekly_report()
    fresh_sources()
    IngestionRun.objects.filter(house="camara").update(status="failed", error_count=1)
    tasks.finish_weekly_collection()
    report = WeeklyReport.objects.get(pk=report_id)
    assert report.status == WeeklyReport.Status.COLLECTING
    assert not report.collection["discovery"]["camara"]["ok"]
    assert report.collection["discovery"]["senado"]["ok"]


@pytest.mark.django_db
def test_dry_run_never_persists_or_calls_external_services(monkeypatch):
    prop()
    refresh = Mock()
    monkeypatch.setattr(
        "apps.newsletters.management.commands.weekly_newsletter.refresh_batch", refresh
    )
    output = StringIO()
    call_command("weekly_newsletter", week_start=date(2026, 9, 28), dry_run=True, stdout=output)
    assert "Radar da Câmara" in output.getvalue()
    assert WeeklyReport.objects.count() == 0
    refresh.assert_not_called()


@pytest.mark.django_db
def test_manual_period_includes_both_tuesdays_and_reuses_frozen_report(monkeypatch, settings):
    settings.WEEKLY_NEWSLETTER_ENABLED = False
    monkeypatch.setattr(timezone, "now", lambda: datetime(2026, 10, 6, 13, tzinfo=REPORT_TZ))
    start = prop(11)
    start.presented_at = date(2026, 9, 29)
    start.save()
    end = prop(12)
    end.presented_at = date(2026, 10, 6)
    end.save()
    for number, day in [(13, date(2026, 9, 28)), (14, date(2026, 10, 7))]:
        outside = prop(number)
        outside.presented_at = day
        outside.save()
    command_module = "apps.newsletters.management.commands.weekly_newsletter"
    refresh = Mock(side_effect=lambda ids: {str(pk): "ok" for pk in ids})
    monkeypatch.setattr(f"{command_module}.refresh_batch", refresh)

    def mark_delivered(pk):
        report = WeeklyReport.objects.get(pk=pk)
        report.status = WeeklyReport.Status.DELIVERED
        report.draft_url = "https://elasnocongresso.substack.com/publish/post/123"
        report.save()
        return report

    delivery = Mock(side_effect=mark_delivered)
    monkeypatch.setattr(f"{command_module}.deliver_report", delivery)
    args = {
        "start_date": date(2026, 9, 29),
        "end_date": date(2026, 10, 6),
        "refresh": True,
        "deliver": True,
    }
    output = StringIO()
    call_command("weekly_newsletter", **args, stdout=output)
    report = WeeklyReport.objects.get()
    assert report.week_end == date(2026, 10, 7)
    assert report.title.endswith("29/09/2026 a 06/10/2026")
    assert report.is_complete
    assert {entry["id"] for entry in report.snapshot} == {start.pk, end.pk}
    assert report.draft_url in output.getvalue()
    assert "2 proposições; coleta completa" in output.getvalue()
    refresh.reset_mock()
    call_command("weekly_newsletter", **args, stdout=StringIO())
    refresh.assert_not_called()
    assert WeeklyReport.objects.count() == 1


@pytest.mark.parametrize(
    "options",
    [
        {"start_date": date(2026, 9, 29)},
        {"end_date": date(2026, 10, 6)},
        {"start_date": date(2026, 10, 6), "end_date": date(2026, 9, 29)},
        {"start_date": date(2026, 9, 29), "end_date": date(2026, 10, 7)},
        {
            "start_date": date(2026, 9, 29),
            "end_date": date(2026, 10, 6),
            "week_start": date(2026, 9, 28),
        },
        {"start_date": date(2026, 9, 29), "end_date": date(2026, 10, 6), "report_id": 1},
        {"week_start": date(2026, 9, 29)},
        {"week_start": date(2026, 10, 5)},
    ],
)
def test_invalid_dates_fail_before_external_calls_or_database_writes(monkeypatch, options):
    monkeypatch.setattr(timezone, "now", lambda: datetime(2026, 10, 6, 13, tzinfo=REPORT_TZ))
    with pytest.raises(CommandError):
        call_command("weekly_newsletter", **options, stdout=StringIO())


@pytest.mark.django_db
def test_same_start_with_different_end_is_rejected_without_delivery(monkeypatch):
    monkeypatch.setattr(timezone, "now", lambda: datetime(2026, 10, 6, 13, tzinfo=REPORT_TZ))
    original = get_report(date(2026, 9, 29), date(2026, 10, 6))
    delivery = Mock()
    monkeypatch.setattr(
        "apps.newsletters.management.commands.weekly_newsletter.deliver_report", delivery
    )
    with pytest.raises(CommandError, match="outra data final"):
        call_command(
            "weekly_newsletter",
            start_date=date(2026, 9, 29),
            end_date=date(2026, 10, 6),
            deliver=True,
        )
    delivery.assert_not_called()
    original.refresh_from_db()
    assert original.week_end == date(2026, 10, 6)
    assert WeeklyReport.objects.count() == 1


@pytest.mark.django_db
def test_staff_export_requires_model_permission(client):
    report = freeze_report(get_report(date(2026, 9, 28), date(2026, 10, 5)).pk, True)
    user = User.objects.create_user(username="editor", is_staff=True)
    client.force_login(user)
    url = reverse("admin:newsletters_weeklyreport_export", args=[report.pk, "markdown"])
    assert client.get(url).status_code == 403
    user.user_permissions.add(Permission.objects.get(codename="view_weeklyreport"))
    response = client.get(url)
    assert response.status_code == 200
    assert response["Content-Disposition"].endswith('.md"')
    assert "LEGENDA" in response.content.decode()


@pytest.mark.django_db
def test_database_enforces_one_report_per_publication_week():
    report = get_report(date(2026, 9, 28), date(2026, 10, 5))
    with pytest.raises(IntegrityError), transaction.atomic():
        WeeklyReport.objects.create(
            publication_url=report.publication_url,
            week_start=report.week_start,
            week_end=report.week_end,
            title="Duplicate",
        )


@pytest.mark.django_db
def test_disable_stops_queued_automatic_deliveries_but_allows_manual(monkeypatch, settings):
    settings.WEEKLY_NEWSLETTER_ENABLED = False
    report = freeze_report(get_report(date(2026, 9, 28), date(2026, 10, 5)).pk, True)
    deliver = Mock(return_value=report)
    monkeypatch.setattr(tasks, "deliver_report", deliver)
    tasks.deliver_weekly_report(report.pk)
    deliver.assert_not_called()
    tasks.deliver_weekly_report(report.pk, manual=True)
    deliver.assert_called_once_with(report.pk)


@pytest.mark.django_db
def test_refresh_records_source_failures_without_losing_success(monkeypatch):
    camara_prop = prop(is_approved=False)
    senate_prop = Proposition.objects.create(
        house="senado",
        external_id=22,
        type_code="PL",
        number_label="PL 22/2026",
        number=22,
        year=2026,
        presented_at=date(2026, 9, 30),
        ementa="Senado",
    )
    camara = Mock()
    camara.fetch_detail.return_value = {
        "statusProposicao": {"codSituacao": 924, "descricaoSituacao": "Pronta para Pauta"}
    }
    camara.fetch_tramitations.return_value = [
        {
            "sequencia": 1,
            "dataHora": "2026-09-30T12:00:00",
            "codSituacao": 924,
            "descricaoSituacao": "Pronta para Pauta",
        }
    ]
    manager = Mock(__enter__=Mock(return_value=camara), __exit__=Mock(return_value=False))
    monkeypatch.setattr(collection, "CamaraClient", Mock(return_value=manager))
    monkeypatch.setattr(collection, "SenadoClient", Mock(return_value=manager))
    results = collection.refresh_batch([camara_prop.pk, senate_prop.pk])
    assert results == {str(camara_prop.pk): "ok", str(senate_prop.pk): "missing_process_id"}
    camara_prop.refresh_from_db()
    assert camara_prop.is_approved is False
    assert camara_prop.events.count() == 1
    collection.refresh_batch([camara_prop.pk])
    assert camara_prop.events.count() == 1
