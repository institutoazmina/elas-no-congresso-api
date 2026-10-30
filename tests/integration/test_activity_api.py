from datetime import timedelta

import pytest
from django.core.cache import cache
from django.test import Client
from django.utils import timezone

from apps.propositions.models import (
    AssessmentOrganization,
    Proposition,
    PropositionAnalysis,
    PropositionAnnotation,
    PropositionEvent,
)
from apps.taxonomy.models import PropositionTheme, Theme


@pytest.fixture(autouse=True)
def clear_activity_cache():
    cache.clear()


@pytest.fixture(autouse=True)
def published_activity_fixture_defaults(monkeypatch):
    """Os cenários legados deste módulo descrevem proposições já publicadas."""
    monkeypatch.setattr(Proposition._meta.get_field("is_approved"), "default", True)
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
    compact_listing = client.get("/api/v1/activity/", {"include_events": "false"})
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
    assert compact_listing.status_code == 200
    assert compact_listing.json()[0]["events"] == []
    assert len(compact_listing.content) < len(listing.content)
    assert detail.status_code == 200
    assert detail.json()["events"][0]["committee_acronym"] == "CCJ"
    assert detail.json()["events"][0]["title"] == "Em pauta"
    assert detail.json()["events"][0]["description"] == "Matéria incluída em pauta para votação."
    assert detail.json()["events"][0]["url"] == "https://www.camara.leg.br/propostas-legislativas/777"
    assert by_number.status_code == 200
    assert by_number.json()["id"] == proposition.pk
    assert cors_by_number["Access-Control-Allow-Origin"] == "https://www.elasnocongresso.com.br"


@pytest.mark.django_db
def test_activity_only_exposes_approved_supported_types_and_automatic_quiteria_assessment():
    visible = Proposition.objects.create(
        external_id=7799,
        house="camara",
        type_code="PL",
        number_label="PL 7799/2026",
        number=7799,
        year=2026,
        presented_at=timezone.localdate(),
        ementa="Proteção contra violência de gênero",
        is_approved=True,
    )
    PropositionAnalysis.objects.create(
        proposition=visible,
        analysis_status=PropositionAnalysis.Status.SUCCEEDED,
        classification=1,
        theme_category="violencias_de_genero",
    )
    theme = Theme.objects.create(slug="violencia-domestica", name="Violência Doméstica")
    PropositionTheme.objects.create(proposition=visible, theme=theme)
    pending = Proposition.objects.create(
        external_id=7800,
        house="camara",
        type_code="PL",
        number_label="PL 7800/2026",
        number=7800,
        year=2026,
        presented_at=timezone.localdate(),
        ementa="Ainda sem curadoria",
        is_approved=False,
    )
    unsupported = Proposition.objects.create(
        external_id=7801,
        house="camara",
        type_code="SBT",
        number_label="SBT 1/2026",
        number=1,
        year=2026,
        presented_at=timezone.localdate(),
        ementa="Documento acessório",
        is_approved=True,
    )

    response = Client().get("/api/v1/activity/", {"include_events": "false"})

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": visible.pk,
            "house": "camara",
            "current_house": "camara",
            "number_label": "PL 7799/2026",
            "ementa": "Proteção contra violência de gênero",
            "presented_at": timezone.localdate().isoformat(),
            "current_status": None,
            "tramitation_url": None,
            "category": "violencias_de_genero",
            "category_label": "Violências de Gênero",
            "themes": ["Violência Doméstica"],
            "is_favorable": False,
            "assessment_organization": "QuitérIA",
            "assessment_comments": None,
            "relevance": None,
            "authors": [],
            "celerity": {
                "label": "Rápida",
                "days_without_movement": 0,
                "movements_last_90_days": 0,
                "last_event_at": None,
            },
            "events": [],
        }
    ]
    assert Client().get(f"/api/v1/activity/{pending.pk}").status_code == 404
    assert Client().get(f"/api/v1/activity/{unsupported.pk}").status_code == 404


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

    # QuerySet.update não dispara signals: a resposta seguinte deve vir do cache.
    Proposition.objects.filter(pk=fast_unfavorable.pk).update(is_approved=False)
    cached = Client().get("/api/v1/activity/fast-unfavorable")

    assert cached.json() == response.json()


@pytest.mark.django_db
def test_fast_unfavorable_activity_orders_by_recent_countable_movements():
    organization = AssessmentOrganization.objects.create(name="AzMina")
    today = timezone.localdate()
    now = timezone.now()
    proposals = []
    for number, movement_count in enumerate([1, 3, 20, 6, 20], start=790):
        proposition = Proposition.objects.create(
            external_id=number,
            house="camara",
            type_code="PL",
            number_label=f"PL {number}/2026",
            number=number,
            year=2026,
            presented_at=today,
            ementa="Proposição desfavorável em tramitação",
        )
        PropositionAnnotation.objects.create(
            proposition=proposition, organization=organization, is_favorable=False, category="saude"
        )
        PropositionEvent.objects.bulk_create([
            PropositionEvent(proposition=proposition, event_at=now - timedelta(days=sequence))
            for sequence in range(movement_count)
        ])
        proposals.append(proposition)

    # Neither older movements nor administrative events should promote the 1-movement PL.
    PropositionEvent.objects.bulk_create([
        PropositionEvent(proposition=proposals[0], event_at=now - timedelta(days=100 + sequence))
        for sequence in range(30)
    ] + [
        PropositionEvent(proposition=proposals[0], event_at=now, is_countable=False)
        for _ in range(30)
    ])
    response = Client().get("/api/v1/activity/fast-unfavorable")
    assert response.status_code == 200
    items = response.json()
    assert [item["id"] for item in items] == [
        proposals[index].pk for index in [2, 4, 3, 1, 0]
    ]
    assert [item["celerity"]["movements_last_90_days"] for item in items] == [20, 20, 6, 3, 1]
    assert Client().get("/api/v1/activity/fast-unfavorable").json() == items


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


@pytest.mark.django_db
def test_enacted_projects_returns_a_shared_complete_contract_for_both_houses():
    organization = AssessmentOrganization.objects.create(name="AzMina")
    propositions = [
        Proposition.objects.create(
            external_id=1001,
            house="camara",
            type_code="PL",
            number_label="PL 1001/2026",
            number=1001,
            year=2026,
            presented_at=timezone.localdate(),
            ementa="Proteção das mulheres",
            current_status="Transformado em Norma Jurídica",
            current_status_code=1140,
            enacted_law_type="Lei Ordinária",
            enacted_law_number=15421,
            enacted_law_year=2026,
            enacted_at=timezone.localdate(),
        ),
        Proposition.objects.create(
            external_id=1002,
            house="senado",
            type_code="PLS",
            number_label="PLS 1002/2026",
            number=1002,
            year=2026,
            presented_at=timezone.localdate(),
            ementa="Combate à violência contra a mulher",
            current_status="TRANSFORMADA EM NORMA JURÍDICA COM VETO PARCIAL",
            current_status_code=92,
            enacted_law_type="Lei Ordinária",
            enacted_law_number=15420,
            enacted_law_year=2026,
            enacted_at=timezone.localdate() - timedelta(days=1),
        ),
    ]
    for proposition, is_favorable in zip(propositions, (True, False), strict=True):
        PropositionAnnotation.objects.create(
            proposition=proposition,
            organization=organization,
            is_favorable=is_favorable,
            category="saude",
        )

    response = Client().get("/api/v1/activity/enacted-projects", {"limit": 1})

    assert response.status_code == 200
    assert response.json() == [
        {
            "id": propositions[0].pk,
            "house": "camara",
            "current_house": "camara",
            "number_label": "PL 1001/2026",
            "ementa": "Proteção das mulheres",
            "presented_at": timezone.localdate().isoformat(),
            "current_status": "Transformado em Norma Jurídica",
            "tramitation_url": None,
            "category": "saude",
            "category_label": "Saúde",
            "themes": [],
            "is_favorable": True,
            "assessment_organization": "AzMina",
            "assessment_comments": None,
            "relevance": "relevante",
            "authors": [],
            "celerity": {
                "label": "Rápida",
                "days_without_movement": 0,
                "movements_last_90_days": 0,
                "last_event_at": None,
            },
            "events": [],
            "assessment_label": "favorável",
            "enactment": {
                "status_code": 1140,
                "status": "Transformado em Norma Jurídica",
                "law_label": "Lei Ordinária 15.421/2026",
                "law_type": "Lei Ordinária",
                "law_number": 15421,
                "law_year": 2026,
                "enacted_at": timezone.localdate().isoformat(),
            },
        }
    ]

    response = Client().get("/api/v1/activity/enacted-projects")
    items = response.json()
    assert [item["house"] for item in items] == ["camara", "senado"]
    assert set(items[0]) == set(items[1])
    assert items[1]["assessment_label"] == "desfavorável"
    assert items[1]["enactment"]["status_code"] == 92


def _public_proposition(external_id=901):
    return Proposition.objects.create(
        external_id=external_id,
        house="camara",
        type_code="PL",
        number_label=f"PL {external_id}/2026",
        number=external_id,
        year=2026,
        presented_at=timezone.localdate(),
        ementa="Proteção das mulheres",
        current_status="Em tramitação",
    )


@pytest.mark.django_db
def test_excluir_anotacao_invalida_o_cache_da_proposicao():
    proposition = _public_proposition()
    organization = AssessmentOrganization.objects.create(name="AzMina")
    annotation = PropositionAnnotation.objects.create(
        proposition=proposition, organization=organization, category="saude", is_favorable=False
    )
    client = Client()
    assert client.get(f"/api/v1/activity/{proposition.pk}").json()["is_favorable"] is False

    annotation.delete()

    assert client.get(f"/api/v1/activity/{proposition.pk}").json()["is_favorable"] is None


@pytest.mark.django_db
def test_renomear_tema_no_admin_invalida_o_cache(
    rf, admin_user, django_capture_on_commit_callbacks
):
    from django.contrib import admin

    proposition = _public_proposition()
    theme = Theme.objects.create(slug="saude", name="Saúde")
    PropositionTheme.objects.create(proposition=proposition, theme=theme)
    client = Client()
    client.get("/api/v1/activity/explorer")
    assert cache.get("activity:explorer:source:v3") is not None

    theme.name = "Saúde da mulher"
    request = rf.post("/")
    request.user = admin_user
    with django_capture_on_commit_callbacks(execute=True):
        admin.site._registry[Theme].save_model(request, theme, None, True)

    assert cache.get("activity:explorer:source:v3") is None
