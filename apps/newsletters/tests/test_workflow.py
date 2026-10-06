from datetime import date, datetime
from io import StringIO
from unittest.mock import Mock

import pytest
from django.contrib.auth.models import Permission, User
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from apps.ingestion.models import IngestionRun
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


@pytest.mark.django_db
def test_batched_collection_includes_unapproved_and_morning_additions(clock, monkeypatch, settings):
    first = prop(is_approved=False, is_active=False)
    report_id = tasks.prepare_weekly_report()
    assert tasks.prepare_weekly_report() == report_id
    settings.WEEKLY_NEWSLETTER_BATCH_SIZE = 1
    refresh = Mock(return_value={str(first.pk): "ok"})
    monkeypatch.setattr(tasks, "refresh_batch", refresh)
    tasks.refresh_weekly_batch(report_id)
    refresh.assert_called_once_with([first.pk])
    second = prop(2)
    monkeypatch.setattr(timezone, "now", lambda: datetime(2026, 10, 5, 6, 36, tzinfo=REPORT_TZ))
    for house in ("camara", "senado"):
        IngestionRun.objects.create(
            house=house,
            window_start=date(2026, 10, 4),
            window_end=date(2026, 10, 6),
            status="success",
            error_count=0,
        )
    tasks.finish_weekly_collection()
    report = WeeklyReport.objects.get(pk=report_id)
    assert second.pk in report.collection["targets"]
    assert all(item["ok"] for item in report.collection["discovery"].values())
    refresh.return_value = {str(second.pk): "ok"}
    tasks.refresh_weekly_batch(report_id)
    monkeypatch.setattr(tasks, "deliver_report", lambda pk: WeeklyReport.objects.get(pk=pk))
    tasks.deliver_weekly_report(report_id)
    report.refresh_from_db()
    assert report.is_complete
    assert {entry["id"] for entry in report.snapshot} == {first.pk, second.pk}


@pytest.mark.django_db
def test_incomplete_collection_and_deadline_are_visible(clock, monkeypatch):
    prop()
    report_id = tasks.prepare_weekly_report()
    monkeypatch.setattr(timezone, "now", lambda: datetime(2026, 10, 5, 6, 46, tzinfo=REPORT_TZ))
    refresh = Mock()
    monkeypatch.setattr(tasks, "refresh_batch", refresh)
    tasks.refresh_weekly_batch(report_id)
    refresh.assert_not_called()
    monkeypatch.setattr(tasks, "deliver_report", lambda pk: WeeklyReport.objects.get(pk=pk))
    tasks.deliver_weekly_report(report_id)
    report = WeeklyReport.objects.get(pk=report_id)
    assert not report.is_complete
    assert "Coleta incompleta" in report.markdown
    tasks.check_weekly_deadline()
    report.refresh_from_db()
    assert report.deadline_missed


@pytest.mark.django_db
def test_discovery_per_item_errors_make_report_incomplete(clock, monkeypatch):
    report_id = tasks.prepare_weekly_report()
    monkeypatch.setattr(timezone, "now", lambda: datetime(2026, 10, 5, 6, 36, tzinfo=REPORT_TZ))
    IngestionRun.objects.create(
        house="camara",
        window_start=date(2026, 10, 4),
        window_end=date(2026, 10, 6),
        status="success",
        error_count=1,
    )
    tasks.finish_weekly_collection()
    report = WeeklyReport.objects.get(pk=report_id)
    assert report.collection["discovery"]["camara"]["ok"] is False
    assert report.collection["discovery"]["senado"]["ok"] is False


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
