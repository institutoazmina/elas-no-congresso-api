from unittest.mock import Mock, patch

import pytest
from django.test import override_settings
from django.utils import timezone

from apps.ingestion import sync
from apps.ingestion.models import IngestionCheckpoint, IngestionItem, IngestionRun
from apps.propositions.models import ClassificationRequest, Proposition, PropositionDocument

pytestmark = pytest.mark.django_db


def test_manual_enqueue_creates_durable_runs_and_items(django_capture_on_commit_callbacks):
    with (
        patch("apps.ingestion.tasks.sync_daily_batch.delay") as delay,
        django_capture_on_commit_callbacks(execute=True),
    ):
        runs = sync.enqueue_manual_links(
            [("camara", 2632728), ("senado", 167294), ("camara", 2632728)]
        )

    assert [(run.house, run.kind, run.discovery_complete) for run in runs] == [
        ("camara", "manual", True),
        ("senado", "manual", True),
    ]
    assert [(run.house, list(run.items.values_list("external_id", flat=True))) for run in runs] == [
        ("camara", [2632728]),
        ("senado", [167294]),
    ]
    assert [call.args for call in delay.call_args_list] == [(runs[0].pk,), (runs[1].pk,)]


def manual_item(house, external_id):
    today = timezone.localdate()
    run = IngestionRun.objects.create(
        house=house,
        kind="manual",
        window_start=today,
        window_end=today,
        discovery_complete=True,
    )
    return IngestionItem.objects.create(run=run, external_id=external_id)


@pytest.mark.parametrize(
    ("kind", "statuses", "expected_deploys"),
    [
        ("manual", [IngestionItem.Status.SUCCEEDED], 1),
        ("daily", [IngestionItem.Status.SUCCEEDED], 1),
        ("manual", [IngestionItem.Status.SUCCEEDED, IngestionItem.Status.FAILED], 1),
        ("manual", [IngestionItem.Status.FAILED], 0),
        ("reconcile", [IngestionItem.Status.SUCCEEDED], 0),
    ],
)
def test_finished_public_ingestion_enqueues_site_deploy(
    monkeypatch, kind, statuses, expected_deploys
):
    now = timezone.now()
    run = IngestionRun.objects.create(
        house="camara",
        kind=kind,
        window_start=now.date(),
        window_end=now.date(),
        discovery_complete=True,
        checkpoint_until=now,
    )
    if kind == "daily":
        IngestionCheckpoint.objects.create(house=run.house)
    for external_id, status in enumerate(statuses, start=1):
        IngestionItem.objects.create(
            run=run,
            external_id=external_id,
            status=status,
        )
    deploy = Mock()
    monkeypatch.setattr("apps.cms.tasks.enqueue_site_deploy", deploy)

    sync.finish_run(run)

    assert deploy.call_count == expected_deploys


def test_manual_camara_item_skips_relevance_and_approves_new_proposition(monkeypatch):
    item = manual_item("camara", 2632728)
    client = Mock()
    client.fetch_detail.return_value = {
        "id": 2632728,
        "siglaTipo": "PL",
        "numero": 123,
        "ano": 2026,
        "dataApresentacao": "2026-10-01",
        "ementa": "Altera uma regra geral sem termos do filtro.",
        "urlInteiroTeor": "https://www.camara.leg.br/documento.pdf",
    }
    client.fetch_tramitations.return_value = []
    client.fetch_authors.return_value = []
    client.fetch_related.return_value = []
    monkeypatch.setattr(sync, "_documents", Mock())
    monkeypatch.setattr(sync, "_discovery_relevance", Mock(side_effect=AssertionError))

    prop = sync.sync_item(item, client, reconcile=True)
    prop.refresh_from_db()

    assert prop.is_approved
    assert prop.house == "camara" and prop.external_id == 2632728
    assert prop.reconciled_at is not None
    sync._documents.assert_called_once()
    assert sync._documents.call_args.kwargs["verify"] is True
    assert sync._documents.call_args.kwargs["baseline"] is False


def test_manual_senado_item_resolves_process_and_approves(monkeypatch):
    item = manual_item("senado", 167294)
    client = Mock()
    client.find_process.return_value = {
        "id": 8796023,
        "identificacao": "PL 592/2025",
        "dataApresentacao": "2025-02-20",
        "ementa": "Altera regra geral sem termos do filtro.",
    }
    client.fetch_process.return_value = {
        "conteudo": {"ementa": "Altera regra geral sem termos do filtro."},
        "situacaoAtual": "Em tramitação",
        "tramitando": "Sim",
        "autuacoes": [],
    }
    client.fetch_authors.return_value = []
    monkeypatch.setattr(sync, "_documents", Mock())
    monkeypatch.setattr(sync, "_discovery_relevance", Mock(side_effect=AssertionError))

    prop = sync.sync_item(item, client, reconcile=True)

    assert prop.is_approved
    assert prop.number_label == "PL 592/2025"
    assert prop.raw_payload["_senado_process_id"] == 8796023
    client.find_process.assert_called_once_with(167294)
    client.fetch_process.assert_called_once_with(8796023)
    sync._documents.assert_called_once()


def test_manual_reingestion_approves_existing_proposition(monkeypatch):
    prop = Proposition.objects.create(
        house="camara",
        external_id=2632728,
        type_code="PL",
        number_label="PL 123/2026",
        number=123,
        year=2026,
        presented_at="2026-10-01",
        ementa="Texto anterior",
    )
    item = manual_item("camara", prop.external_id)
    client = Mock()
    client.fetch_detail.return_value = {
        "id": prop.external_id,
        "siglaTipo": "PL",
        "numero": 123,
        "ano": 2026,
        "dataApresentacao": "2026-10-01",
        "ementa": "Texto atualizado",
    }
    client.fetch_tramitations.return_value = []
    client.fetch_authors.return_value = []
    client.fetch_related.return_value = []
    monkeypatch.setattr(sync, "_documents", Mock())

    sync.sync_item(item, client, reconcile=True)
    prop.refresh_from_db()

    assert prop.is_approved
    assert prop.ementa == "Texto atualizado"


def test_manual_camara_document_is_queued_for_extraction(django_capture_on_commit_callbacks):
    item = manual_item("camara", 2632728)
    client = Mock()
    client.fetch_detail.return_value = {
        "id": item.external_id,
        "siglaTipo": "PL",
        "numero": 123,
        "ano": 2026,
        "dataApresentacao": "2026-10-01",
        "ementa": "Altera uma regra geral.",
        "urlInteiroTeor": "https://www.camara.leg.br/documento.pdf",
    }
    client.fetch_tramitations.return_value = []
    client.fetch_authors.return_value = []
    client.fetch_related.return_value = []
    with (
        patch("apps.ingestion.tasks.check_proposition_document.delay") as extract,
        patch("apps.subscriptions.tasks.match_and_notify.delay"),
        django_capture_on_commit_callbacks(execute=True),
    ):
        prop = sync.sync_item(item, client, reconcile=True)

    document = PropositionDocument.objects.get(proposition=prop, role="original")
    assert document.status == document.Status.PENDING
    extract.assert_called_once_with(document.pk)


@override_settings(QUITERIA_ENABLED=True)
def test_manual_without_document_queues_ai_from_ementa(django_capture_on_commit_callbacks):
    item = manual_item("camara", 2632728)
    client = Mock()
    client.fetch_detail.return_value = {
        "id": item.external_id,
        "siglaTipo": "PL",
        "numero": 123,
        "ano": 2026,
        "dataApresentacao": "2026-10-01",
        "ementa": "Altera uma regra geral.",
    }
    client.fetch_tramitations.return_value = []
    client.fetch_authors.return_value = []
    client.fetch_related.return_value = []
    with (
        patch("apps.ingestion.tasks.run_classification_request.delay") as classify,
        patch("apps.subscriptions.tasks.match_and_notify.delay"),
        django_capture_on_commit_callbacks(execute=True),
    ):
        prop = sync.sync_item(item, client, reconcile=True)

    request = ClassificationRequest.objects.get(proposition=prop)
    assert request.status == request.Status.PENDING
    classify.assert_called_once_with(request.pk)
