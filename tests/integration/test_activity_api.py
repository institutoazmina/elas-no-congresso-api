from datetime import timedelta

import pytest
from django.core.cache import cache
from django.core.management import call_command
from django.test import Client
from django.utils import timezone

from apps.legislatures.models import Parliamentarian
from apps.propositions.models import (
    AssessmentOrganization,
    Proposition,
    PropositionAnnotation,
    PropositionAuthor,
    PropositionEvent,
)


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
            dispatch="Matéria incluída em pauta para votação.",
            committee_acronym="CCJ",
            raw_payload={"url": "https://www.camara.leg.br/propostas-legislativas/777"},
        )

    client = Client()
    listing = client.get("/api/v1/activity/")
    detail = client.get(f"/api/v1/activity/{proposition.pk}")
    by_number = client.get(
        "/api/v1/activity/by-number",
        {"house": proposition.house, "number_label": proposition.number_label},
    )
    cors_by_number = client.get(
        "/api/v1/activity/by-number",
        {"house": proposition.house, "number_label": proposition.number_label},
        HTTP_ORIGIN="https://www.elasnocongresso.com.br",
    )

    assert listing.status_code == 200
    assert listing.json()[0]["celerity"]["label"] == "Tá voando"
    assert len(listing.json()[0]["events"]) == 3
    assert detail.status_code == 200
    assert detail.json()["events"][0]["committee_acronym"] == "CCJ"
    assert detail.json()["events"][0]["title"] == "Em pauta"
    assert detail.json()["events"][0]["description"] == "Matéria incluída em pauta para votação."
    assert detail.json()["events"][0]["url"] == "https://www.camara.leg.br/propostas-legislativas/777"
    assert by_number.status_code == 200
    assert by_number.json()["id"] == proposition.pk
    assert cors_by_number["Access-Control-Allow-Origin"] == "https://www.elasnocongresso.com.br"


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


@pytest.mark.django_db
def test_legacy_profile_sync_adds_missing_author_photo_to_activity(tmp_path):
    photo_url = "https://www.camara.leg.br/internet/deputado/bandep/74052.jpg"
    csv_path = tmp_path / "parlamentares.csv"
    csv_path.write_text(
        "nome,numero,foto,genero,partido,cargo,estado,legislatura\n"
        f'"Bosco Costa",74052,{photo_url},M,PROS,Deputado,SE,56.57\n',
        encoding="utf-8",
    )
    parliamentarian = Parliamentarian.objects.create(full_name="Bosco Costa", gender="M")
    proposition = Proposition.objects.create(
        external_id=505,
        house="camara",
        type_code="PL",
        number_label="PL 505/2020",
        number=505,
        year=2020,
        presented_at=timezone.localdate(),
        ementa="Proteção das mulheres",
    )
    PropositionAuthor.objects.create(proposition=proposition, parliamentarian=parliamentarian)

    initial = Client().get(f"/api/v1/activity/{proposition.pk}")
    assert initial.json()["authors"][0]["photo_url"] is None

    call_command("sync_legacy_parliamentarian_profiles", csv_path=str(csv_path))

    response = Client().get(f"/api/v1/activity/{proposition.pk}")

    assert response.status_code == 200
    assert response.json()["authors"] == [
        {
            "id": parliamentarian.pk,
            "name": "Bosco Costa",
            "party": None,
            "state": None,
            "gender": "M",
            "photo_url": photo_url,
            "role": None,
        }
    ]


@pytest.mark.django_db
def test_fast_unfavorable_activity_only_returns_fast_unfavorable_propositions():
    organization = AssessmentOrganization.objects.create(name="AzMina")
    fast_unfavorable = Proposition.objects.create(
        external_id=779,
        house="camara",
        type_code="PL",
        number_label="PL 779/2026",
        number=779,
        year=2026,
        presented_at=timezone.localdate(),
        ementa="Proteção das mulheres",
    )
    flying_unfavorable = Proposition.objects.create(
        external_id=780,
        house="camara",
        type_code="PL",
        number_label="PL 780/2026",
        number=780,
        year=2026,
        presented_at=timezone.localdate(),
        ementa="Proteção das mulheres",
    )
    slow_unfavorable = Proposition.objects.create(
        external_id=781,
        house="camara",
        type_code="PL",
        number_label="PL 781/2026",
        number=781,
        year=2026,
        presented_at=timezone.localdate() - timedelta(days=100),
        ementa="Proteção das mulheres",
    )
    favorable = Proposition.objects.create(
        external_id=782,
        house="camara",
        type_code="PL",
        number_label="PL 782/2026",
        number=782,
        year=2026,
        presented_at=timezone.localdate(),
        ementa="Proteção das mulheres",
    )
    for proposition, is_favorable in ((fast_unfavorable, False), (flying_unfavorable, False), (slow_unfavorable, False), (favorable, True)):
        PropositionAnnotation.objects.create(
            proposition=proposition,
            organization=organization,
            is_favorable=is_favorable,
            category="saude",
        )
    PropositionEvent.objects.create(proposition=fast_unfavorable, event_at=timezone.now())
    for sequence in range(3):
        PropositionEvent.objects.create(
            proposition=flying_unfavorable,
            event_at=timezone.now() - timedelta(days=sequence),
        )
    PropositionEvent.objects.create(
        proposition=slow_unfavorable,
        event_at=timezone.now() - timedelta(days=100),
    )
    for sequence in range(3):
        PropositionEvent.objects.create(
            proposition=favorable,
            event_at=timezone.now() - timedelta(days=sequence),
        )

    response = Client().get("/api/v1/activity/fast-unfavorable")

    assert response.status_code == 200
    assert [item["number_label"] for item in response.json()] == ["PL 780/2026", "PL 779/2026"]
    assert {item["celerity"]["label"] for item in response.json()} == {"Rápida", "Tá voando"}
    assert all(item["is_favorable"] is False for item in response.json())

    fast_unfavorable.delete()
    cached = Client().get("/api/v1/activity/fast-unfavorable")

    assert cached.json() == response.json()


@pytest.mark.django_db
def test_slow_favorable_activity_returns_the_50_most_inactive_qualifying_propositions():
    organization = AssessmentOrganization.objects.create(name="AzMina")
    slow_favorable = []
    for sequence in range(51):
        proposition = Proposition.objects.create(
            external_id=800 + sequence,
            house="camara",
            type_code="PL",
            number_label=f"PL {800 + sequence}/2026",
            number=800 + sequence,
            year=2026,
            presented_at=timezone.localdate() - timedelta(days=90 + sequence),
            ementa="Proteção das mulheres",
        )
        PropositionAnnotation.objects.create(
            proposition=proposition,
            organization=organization,
            is_favorable=True,
            category="saude",
        )
        slow_favorable.append(proposition)

    blocked = Proposition.objects.create(
        external_id=899,
        house="camara",
        type_code="PL",
        number_label="PL 899/2026",
        number=899,
        year=2026,
        presented_at=timezone.localdate() - timedelta(days=200),
        ementa="Proteção das mulheres",
    )
    forgotten = Proposition.objects.create(
        external_id=900,
        house="camara",
        type_code="PL",
        number_label="PL 900/2026",
        number=900,
        year=2026,
        presented_at=timezone.localdate() - timedelta(days=360),
        ementa="Proteção das mulheres",
    )
    unfavorable = Proposition.objects.create(
        external_id=901,
        house="camara",
        type_code="PL",
        number_label="PL 901/2026",
        number=901,
        year=2026,
        presented_at=timezone.localdate() - timedelta(days=200),
        ementa="Proteção das mulheres",
    )
    for proposition, is_favorable in ((blocked, True), (forgotten, True), (unfavorable, False)):
        PropositionAnnotation.objects.create(
            proposition=proposition,
            organization=organization,
            is_favorable=is_favorable,
            category="saude",
        )

    response = Client().get("/api/v1/activity/slow-favorable")

    assert response.status_code == 200
    assert len(response.json()) == 50
    assert [item["number_label"] for item in response.json()] == [
        blocked.number_label,
        *(proposition.number_label for proposition in reversed(slow_favorable[2:])),
    ]
    assert {item["celerity"]["label"] for item in response.json()} == {"Lenta", "Travada"}
    assert all(item["is_favorable"] is True for item in response.json())
