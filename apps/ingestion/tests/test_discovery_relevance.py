from unittest.mock import Mock

import httpx
import pytest

from apps.ingestion import tasks
from apps.ingestion.fulltext import extract_pdf_text
from apps.ingestion.models import IngestionRun
from apps.ingestion.tests.test_tasks import _FakeCamara, _FakeSenado
from apps.propositions.models import Proposition

pytestmark = pytest.mark.django_db


@pytest.fixture(params=["camara", "senado"])
def discovery(request, monkeypatch):
    house = request.param
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
