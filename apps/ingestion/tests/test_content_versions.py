from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.ingestion import content, tasks
from apps.ingestion.sync import _documents
from apps.propositions.models import (
    ClassificationRequest,
    Proposition,
    PropositionAnalysis,
    PropositionContentVersion,
)

pytestmark = pytest.mark.django_db


def fields():
    return {
        "house": "camara",
        "external_id": 77,
        "type_code": "PL",
        "number_label": "PL 77/2026",
        "number": 77,
        "year": 2026,
        "presented_at": date(2026, 10, 1),
        "ementa": "Proteção das mulheres",
    }


@pytest.fixture
def ai(monkeypatch, settings):
    settings.QUITERIA_ENABLED = True
    queued = Mock()
    monkeypatch.setattr(tasks.run_classification_request, "delay", queued)
    monkeypatch.setattr(tasks.check_proposition_document, "delay", Mock())
    prediction = SimpleNamespace(
        theme_category="saude",
        theme_confidence=0.9,
        theme_scores={},
        favorability_probability=0.3,
        favorability_scores={},
    )
    model = Mock()
    model.classify.return_value = prediction
    monkeypatch.setattr("apps.propositions.quiteria.get_classifier", lambda: model)
    return model, queued


def pdf_transport(monkeypatch, body):
    original = httpx.Client
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, content=body[0], headers={"ETag": str(body[0])})

    extract = Mock(side_effect=lambda raw, url: raw.decode().split("|")[0])
    monkeypatch.setattr("apps.ingestion.fulltext._extract", extract)
    monkeypatch.setattr(
        content.httpx,
        "Client",
        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs),
    )
    return extract, requests


def test_status_and_author_metadata_do_not_enqueue_ai(ai, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        pk = tasks._persist(fields(), None, [], [])
    request = ClassificationRequest.objects.get()
    content.run_analysis(request.pk)
    PropositionAnalysis.objects.filter(proposition_id=pk).update(expert_opinion="Revisão humana")
    ai[1].reset_mock()
    with django_capture_on_commit_callbacks(execute=True):
        tasks._persist(
            {**fields(), "current_status": "Na CCJC", "is_approved": True},
            {"event_at": timezone.now(), "source_event_id": "camara:2", "situation": "Na CCJC"},
            [],
            [],
        )
    ai[1].assert_not_called()
    assert ClassificationRequest.objects.count() == 1
    prop = Proposition.objects.get(pk=pk)
    assert not prop.is_approved
    assert prop.analysis.expert_opinion == "Revisão humana"
    assert prop.events.count() == 1


def test_pdf_hashes_skip_ocr_and_semantically_identical_text_skips_ai(ai, monkeypatch):
    prop = Proposition.objects.create(**fields())
    body = [b"Texto original|PDF1"]
    extract, requests = pdf_transport(monkeypatch, body)
    doc = content.register_document(prop.pk, "original", "original", "https://docs.test/one.pdf")
    assert content.check_document(doc.pk)
    assert ClassificationRequest.objects.count() == 1
    content.register_document(prop.pk, "original", "original", doc.url, verify=True)
    assert content.check_document(doc.pk)
    assert extract.call_count == 1
    assert requests[-1].headers.get("If-None-Match")
    body[0] = b"Texto original|PDF2"
    content.register_document(prop.pk, "original", "original", "https://docs.test/two.pdf")
    assert content.check_document(doc.pk)
    assert "If-None-Match" not in requests[-1].headers
    assert ClassificationRequest.objects.count() == 1
    body[0] = b"Texto alterado|PDF3"
    content.register_document(
        prop.pk, "original", "original", "https://docs.test/two.pdf", revision="new text"
    )
    assert content.check_document(doc.pk)
    assert ClassificationRequest.objects.count() == 2
    assert {v.source_url for v in prop.content_versions.all()} == {
        "https://docs.test/one.pdf",
        "https://docs.test/two.pdf",
    }


def test_replacements_exclude_reports_and_partial_amendments(ai):
    prop = Proposition.objects.create(**{**fields(), "house": "senado"})
    client = Mock()
    client.fetch_documents.return_value = [
        {
            "id": 1,
            "siglaTipo": "PARECER_REDACAO",
            "descricaoTipo": "Parecer",
            "descricao": "Substitutivo",
            "urlDocumento": "https://docs.test/report",
        },
        {
            "id": 2,
            "siglaTipo": "EMENDA",
            "descricaoTipo": "Emenda",
            "descricao": "Altera artigo 2",
            "urlDocumento": "https://docs.test/partial",
        },
        {
            "id": 3,
            "siglaTipo": "EMENDA",
            "descricaoTipo": "Emenda",
            "descricao": "Texto integral do substitutivo",
            "dataDocumento": "2026-10-06",
            "urlDocumento": "https://docs.test/replacement",
        },
    ]
    _documents(prop, client, [], process_id=55)
    assert list(prop.documents.values_list("source_key", flat=True)) == ["senado:3"]


def test_late_older_document_cannot_replace_newer_text(ai, monkeypatch):
    prop = Proposition.objects.create(**fields())
    body = [b"Texto novo"]
    pdf_transport(monkeypatch, body)
    now = timezone.now()
    newest = content.register_document(
        prop.pk, "sbt2", "replacement", "https://docs.test/new", source_date=now
    )
    content.check_document(newest.pk)
    body[0] = b"Texto antigo"
    older = content.register_document(
        prop.pk, "sbt1", "replacement", "https://docs.test/old", source_date=now - timedelta(days=2)
    )
    content.check_document(older.pk)
    prop.refresh_from_db()
    assert prop.current_content.text == "Texto novo"
    assert ClassificationRequest.objects.count() == 1


def test_old_inflight_prediction_is_not_applied(ai):
    prop = Proposition.objects.create(**fields())
    content.register_fallback(prop.pk, analyze=True)
    request = ClassificationRequest.objects.get()
    newer = PropositionContentVersion.objects.create(
        proposition=prop, text="Novo texto", text_hash=content.text_digest("Novo texto")
    )

    def changed_during_inference(_):
        Proposition.objects.filter(pk=prop.pk).update(current_content=newer)
        return SimpleNamespace(
            theme_category="saude",
            theme_confidence=0.9,
            theme_scores={},
            favorability_probability=0.3,
            favorability_scores={},
        )

    ai[0].classify.side_effect = changed_during_inference
    content.run_analysis(request.pk)
    request.refresh_from_db()
    assert request.status == "superseded"
    assert not PropositionAnalysis.objects.filter(proposition=prop).exists()


def test_baseline_does_not_reclassify_legacy_rows(ai, monkeypatch):
    prop = Proposition.objects.create(**fields())
    content.register_fallback(prop.pk, analyze=False)
    body = ["Texto histórico completo".encode()]
    pdf_transport(monkeypatch, body)
    doc = content.register_document(
        prop.pk, "original", "original", "https://docs.test/doc", analyze_on_first=False
    )
    content.check_document(doc.pk)
    assert not ClassificationRequest.objects.exists()
    body[0] = b"Texto modificado depois da baseline"
    content.register_document(prop.pk, "original", "original", doc.url, verify=True)
    content.check_document(doc.pk)
    assert ClassificationRequest.objects.count() == 1


def test_event_replay_has_constant_queries_and_no_event_updates():
    prop = Proposition.objects.create(**fields())
    events = [
        {"source_event_id": f"camara:{i}", "event_at": timezone.now(), "title": "Movimentação"}
        for i in range(100)
    ]
    tasks._persist_events(prop, events)
    with CaptureQueriesContext(connection) as queries:
        tasks._persist_events(prop, events)
    assert len(queries) < 8
    assert not any('UPDATE "proposition_events"' in q["sql"] for q in queries)
    assert prop.events.count() == 100


@pytest.mark.django_db(transaction=True)
def test_concurrent_content_requests_are_deduplicated(ai):
    prop = Proposition.objects.create(**fields())

    def register(_):
        from django.db import connections

        try:
            content.register_fallback(prop.pk, analyze=True)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(register, range(2)))
    assert ClassificationRequest.objects.count() == 1
    assert PropositionContentVersion.objects.count() == 1
    assert ai[1].call_count == 1
