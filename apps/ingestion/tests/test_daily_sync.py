from collections import Counter
from datetime import date
from unittest.mock import Mock

import pytest

from apps.ingestion import tasks
from apps.ingestion.models import IngestionCheckpoint, IngestionRun
from apps.propositions.models import ClassificationRequest, Proposition


@pytest.mark.django_db
def test_failed_item_is_resumed_without_repeating_success_or_discovery(monkeypatch):
    counts = Counter()
    failing = [True]

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            pass

        def list_propositions(self, start, end):
            counts["discovery"] += 1
            yield {"id": 1, "ementa": "Proteção da mulher"}
            yield {"id": 2, "ementa": "Proteção da mulher"}

        def fetch_detail(self, pk):
            counts[pk] += 1
            if pk == 2 and failing[0]:
                raise RuntimeError("source outage")
            return {
                "id": pk,
                "siglaTipo": "PL",
                "numero": pk,
                "ano": 2026,
                "ementa": "Proteção da mulher",
                "dataApresentacao": "2026-10-01",
            }

        def fetch_authors(self, pk):
            return []

        def fetch_tramitations(self, pk):
            return []

    monkeypatch.setattr(tasks, "CamaraClient", Client)
    run_id = tasks.ingest_camara()
    run = IngestionRun.objects.get(pk=run_id)
    assert run.status == "failed"
    assert not IngestionCheckpoint.objects.get(house="camara").covered_until
    assert counts[1] == 1 and counts[2] == 3
    failing[0] = False
    assert tasks.ingest_camara() == run_id
    run.refresh_from_db()
    assert run.status == "success"
    assert counts[1] == 1 and counts[2] == 4 and counts["discovery"] == 1
    assert IngestionCheckpoint.objects.get(house="camara").covered_until


@pytest.mark.django_db
def test_tracked_older_irrelevant_closed_proposition_is_updated_without_ai(monkeypatch, settings):
    settings.QUITERIA_ENABLED = True
    prop = Proposition.objects.create(
        house="camara",
        external_id=9,
        type_code="PL",
        number_label="PL 9/2010",
        number=9,
        year=2010,
        presented_at=date(2010, 1, 1),
        ementa="Obras públicas",
        is_active=False,
    )
    client = Mock()
    client.list_propositions.return_value = [{"id": 9, "ementa": "Obras públicas"}]
    client.fetch_detail.return_value = {
        "ementa": "Obras públicas",
        "statusProposicao": {"descricaoSituacao": "Na CCJC"},
    }
    client.fetch_authors.return_value = []
    client.fetch_tramitations.return_value = [
        {"sequencia": 1, "dataHora": "2026-10-06T10:00:00", "descricaoSituacao": "Na CCJC"}
    ]
    manager = Mock(__enter__=Mock(return_value=client), __exit__=Mock(return_value=False))
    monkeypatch.setattr(tasks, "CamaraClient", Mock(return_value=manager))
    tasks.ingest_camara()
    prop.refresh_from_db()
    assert prop.current_status == "Na CCJC"
    assert prop.source_checked_at
    assert prop.events.count() == 1
    assert not ClassificationRequest.objects.exists()


@pytest.mark.django_db
def test_baseline_reconciliation_is_batched_and_completes_coverage(monkeypatch, settings):
    from apps.ingestion.tests.test_tasks import _FakeCamara

    settings.INGESTION_BATCH_SIZE = 1
    for pk in (1, 2):
        Proposition.objects.create(
            house="camara",
            external_id=pk,
            type_code="PL",
            number_label=f"PL {pk}/2026",
            number=pk,
            year=2026,
            presented_at=date(2026, 1, 1),
            ementa="Obras públicas",
        )
    monkeypatch.setattr(
        tasks, "CamaraClient", lambda: _FakeCamara({}, {"ementa": "Obras públicas"}, [])
    )
    tasks.reconcile_daily_propositions(full_baseline=True)
    assert Proposition.objects.filter(reconciled_at__isnull=True).count() == 0
    checkpoint = IngestionCheckpoint.objects.get(house="camara")
    assert checkpoint.baseline_complete
    run = IngestionRun.objects.get(house="camara", kind="reconcile")
    assert run.status == "success" and run.processed_count == 2
    assert not checkpoint.covered_until  # A reconciliation is not a successful discovery window.
