from unittest.mock import Mock

import httpx
import pytest

from apps.ingestion import tasks
from apps.ingestion.fulltext import extract_pdf_text
from apps.ingestion.models import IngestionRun
from apps.ingestion.tests.test_tasks import _FakeCamara, _FakeSenado
from apps.propositions.models import IgnoredProposition, Proposition

pytestmark = pytest.mark.django_db


def _discovery(house, monkeypatch):
    summary_text = "Altera a legislação vigente."
    url = "https://legislativo.test/original.pdf"
    if house == "camara":
        summary = {"id": 701, "ementa": summary_text}
        detail = {
            "id": 701,
            "ementa": summary_text,
            "siglaTipo": "PL",
            "numero": 701,
            "ano": 2026,
            "dataApresentacao": "2026-10-01",
            "urlInteiroTeor": url,
            "keywords": "ABORTO",  # Indexation alone must not qualify a proposition.
        }
        client = _FakeCamara(summary, detail, [])
        monkeypatch.setattr(tasks, "CamaraClient", lambda: client)
        task = tasks.ingest_camara
    else:
        data = {
            "identificacao": "PL 701/2026",
            "dataApresentacao": "2026-10-01",
            "ementa": summary_text,
            "urlDocumento": url,
        }
        summary = {
            "IdentificacaoMateria": {"CodigoMateria": "701"},
            "Ementa": summary_text,
            "_process_summary": data,
        }
        client = _FakeSenado(summary, {}, {})
        monkeypatch.setattr(tasks, "SenadoClient", lambda: client)
        task = tasks.ingest_senado
    # The document queue has separate coverage; these tests isolate discovery decisions.
    monkeypatch.setattr("apps.ingestion.sync._documents", Mock())
    extraction = Mock(return_value="O projeto dispõe sobre ADENOMIOSE.")
    monkeypatch.setattr("apps.ingestion.fulltext.extract_pdf_text", extraction)
    return task, client, extraction, house


@pytest.fixture(params=["camara", "senado"])
def discovery(request, monkeypatch):
    return _discovery(request.param, monkeypatch)


@pytest.fixture
def camara_discovery(monkeypatch):
    return _discovery("camara", monkeypatch)


@pytest.fixture
def senado_discovery(monkeypatch):
    return _discovery("senado", monkeypatch)


def test_full_text_only_match_is_persisted(discovery):
    task, client, extraction, house = discovery
    run = IngestionRun.objects.get(pk=task())
    assert run.status == "success"
    prop = Proposition.objects.get(house=house, external_id=701)
    assert prop.full_text == extraction.return_value
    assert prop.proposition_themes.filter(theme__name__iexact="adenomiose").exists()
    extraction.assert_called_once()


def test_negative_full_text_is_skipped(discovery):
    task, client, extraction, house = discovery
    extraction.return_value = "Cultivo de soja transgênica."
    run = IngestionRun.objects.get(pk=task())
    assert run.status == "success"
    assert run.skipped_count == 1
    assert not Proposition.objects.filter(house=house).exists()
    extraction.assert_called_once()


def test_deleted_proposition_is_ignored_by_future_ingestion(discovery):
    task, client, extraction, house = discovery
    proposition = Proposition.objects.create(
        house=house,
        external_id=701,
        type_code="PL",
        number_label="PL 701/2026",
        number=701,
        year=2026,
        presented_at="2026-10-01",
        ementa="Proteção às mulheres.",
    )

    proposition.delete()
    run = IngestionRun.objects.get(pk=task())

    ignored = IgnoredProposition.objects.get(house=house, external_id=701)
    assert ignored.number_label == "PL 701/2026"
    assert run.status == "success"
    assert run.skipped_count == 1 and run.error_count == 0
    assert run.items.get().status == "skipped"
    assert not Proposition.objects.filter(house=house, external_id=701).exists()
    extraction.assert_not_called()


def test_failed_extraction_can_be_resumed(discovery):
    task, client, extraction, house = discovery
    extraction.return_value = None
    run = IngestionRun.objects.get(pk=task())
    assert run.status == "failed" and run.skipped_count == 0
    assert run.items.get().status == "failed"
    assert not Proposition.objects.filter(house=house).exists()
    extraction.return_value = "Atendimento em casos de endometriose."
    assert task() == run.pk
    run.refresh_from_db()
    assert run.status == "success"
    assert Proposition.objects.filter(house=house).exists()


def test_ementa_match_does_not_need_synchronous_pdf(discovery):
    task, client, extraction, house = discovery
    client._s["ementa" if house == "camara" else "Ementa"] = "Proteção às mulheres."
    run = IngestionRun.objects.get(pk=task())
    assert run.status == "success" and run.upserted_count == 1
    extraction.assert_not_called()


@pytest.mark.parametrize("relevant", [False, True])
def test_missing_document_uses_ementa_without_failing_run(discovery, relevant):
    task, client, extraction, house = discovery
    if house == "camara":
        client._d.pop("urlInteiroTeor")
    else:
        client._s["_process_summary"].pop("urlDocumento")
    if relevant:
        client._s["ementa" if house == "camara" else "Ementa"] = "Proteção às mulheres."
    run = IngestionRun.objects.get(pk=task())
    assert run.status == "success" and run.error_count == 0
    assert run.skipped_count == (0 if relevant else 1)
    assert run.upserted_count == (1 if relevant else 0)
    assert run.items.get().attempts == 1
    assert Proposition.objects.filter(house=house, external_id=701).exists() == relevant
    extraction.assert_not_called()


def test_security_challenge_uses_ementa_without_failing_run(discovery):
    task, client, extraction, house = discovery
    transport = httpx.MockTransport(
        lambda request: httpx.Response(
            200, text="<!DOCTYPE html><title>Verificação de segurança — Senado Federal</title>"
        )
    )
    with httpx.Client(transport=transport) as http_client:
        extraction.side_effect = lambda url, **kwargs: extract_pdf_text(
            url, client=http_client, **kwargs
        )
        run = IngestionRun.objects.get(pk=task())
    assert run.status == "success"
    assert run.skipped_count == 1 and run.error_count == 0
    assert run.items.get().attempts == 1
    assert not Proposition.objects.filter(house=house).exists()


def test_empty_camara_document_uses_ementa_without_failing_run(camara_discovery):
    task, client, extraction, house = camara_discovery
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=b""))
    with httpx.Client(transport=transport) as http_client:
        extraction.side_effect = lambda url, **kwargs: extract_pdf_text(
            url, client=http_client, **kwargs
        )
        run = IngestionRun.objects.get(pk=task())
    assert run.status == "success"
    assert run.skipped_count == 1 and run.error_count == 0
    assert run.items.get().attempts == 1
    assert not Proposition.objects.filter(house=house).exists()


def test_rtf_senado_document_is_classified_from_full_text(senado_discovery):
    task, client, extraction, house = senado_discovery
    content = rb"{\rtf1\ansi\ansicpg1252 Altera a lei sobre \b ADENOMIOSE\b0.}"
    transport = httpx.MockTransport(lambda request: httpx.Response(200, content=content))
    with httpx.Client(transport=transport) as http_client:
        extraction.side_effect = lambda url, **kwargs: extract_pdf_text(
            url, client=http_client, **kwargs
        )
        run = IngestionRun.objects.get(pk=task())
    assert run.status == "success"
    proposition = Proposition.objects.get(house=house, external_id=701)
    assert "ADENOMIOSE" in proposition.full_text
    assert proposition.proposition_themes.filter(theme__name__iexact="adenomiose").exists()
