from datetime import timedelta

import pytest
from django.core.cache import cache
from django.test import Client
from django.utils import timezone

from apps.propositions.models import Proposition, PropositionEvent


@pytest.fixture(autouse=True)
def clear_activity_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.mark.django_db
def test_activity_endpoints_return_celerity_preview_and_full_history():
    proposition = Proposition.objects.create(
        external_id=777,
        house="camara",
        type_code="PL",
        number_label="PL 777/2026",
        number=777,
        year=2026,
        presented_at=timezone.localdate() - timedelta(days=100),
        ementa="Proteção das mulheres",
        current_status="Em tramitação",
    )
    for sequence in range(3):
        event_at = timezone.now() - timedelta(days=sequence + 1)
        PropositionEvent.objects.create(
            proposition=proposition,
            source_event_id=f"camara:{sequence}",
            source_kind="tramitation",
            event_at=event_at,
            title="Em pauta",
            description="Matéria incluída em pauta.",
            committee_acronym="CCJ",
        )

    client = Client()
    listing = client.get("/api/v1/activity/")
    detail = client.get(f"/api/v1/activity/{proposition.pk}")
    by_number = client.get(
        "/api/v1/activity/by-number",
        {"house": proposition.house, "number_label": proposition.number_label},
    )

    assert listing.status_code == 200
    assert listing.json()[0]["celerity"]["label"] == "Tá voando"
    assert len(listing.json()[0]["events"]) == 3
    assert detail.status_code == 200
    assert detail.json()["events"][0]["committee_acronym"] == "CCJ"
    assert by_number.status_code == 200
    assert by_number.json()["id"] == proposition.pk


@pytest.mark.django_db
def test_activity_by_number_is_cached():
    proposition = Proposition.objects.create(
        external_id=778,
        house="camara",
        type_code="PL",
        number_label="PL 778/2026",
        number=778,
        year=2026,
        presented_at=timezone.localdate(),
        ementa="Proteção das mulheres",
    )
    PropositionEvent.objects.create(
        proposition=proposition,
        source_event_id="camara:first",
        source_kind="tramitation",
        event_at=timezone.now(),
        title="Em pauta",
    )

    client = Client()
    params = {"house": proposition.house, "number_label": proposition.number_label}
    first = client.get("/api/v1/activity/by-number", params)
    PropositionEvent.objects.create(
        proposition=proposition,
        source_event_id="camara:second",
        source_kind="tramitation",
        event_at=timezone.now(),
        title="Nova movimentação",
    )
    cached = client.get("/api/v1/activity/by-number", params)

    assert first.status_code == 200
    assert cached.status_code == 200
    assert len(cached.json()["events"]) == 1
