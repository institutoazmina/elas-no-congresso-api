from datetime import date, timedelta
from importlib import import_module
from types import SimpleNamespace

import pytest
from django.apps import apps
from django.core.cache import cache
from django.db import connection
from django.utils import timezone

from apps.ingestion.house_transfers import (
    link_pending_senate_transfers,
    link_senate_transfer,
    senate_origin,
)
from apps.ingestion.models import IngestionItem, IngestionRun
from apps.ingestion.sync import sync_item
from apps.legislatures.models import InstitutionalAuthor, Parliamentarian
from apps.propositions.models import (
    AssessmentOrganization,
    Proposition,
    PropositionAnnotation,
    PropositionAuthor,
    PropositionEvent,
)
from apps.subscriptions.models import AlertDelivery, Subscription
from apps.subscriptions.tasks import send_alert_email


def proposition(house, external_id, number, year, **kwargs):
    return Proposition.objects.create(
        house=house,
        external_id=external_id,
        type_code="PL",
        number=number,
        year=year,
        number_label=f"PL {number}/{year}",
        presented_at=date(year, 7, 12) if house == "camara" else date(2026, 10, 20),
        ementa="Orçamento Mulher",
        tramitation_url=f"https://{'www.camara.leg.br' if house == 'camara' else 'www25.senado.leg.br'}/bill/{external_id}",
        current_status="Enviado ao Senado" if house == "camara" else "AGUARDANDO DESPACHO",
        is_approved=True,
        **kwargs,
    )


def event(prop, source_id, days, *, dispatch=None):
    return PropositionEvent.objects.create(
        proposition=prop,
        source_event_id=source_id,
        event_at=timezone.now() - timedelta(days=days),
        title="Movimentação",
        dispatch=dispatch,
        raw_payload={},
    )


@pytest.mark.django_db
def test_two_official_source_records_become_one_public_bill_with_one_timeline():
    original = proposition("camara", 2335003, 2448, 2022)
    senate = proposition(
        "senado",
        176010,
        2448,
        2022,
        originating_house="camara",
        canonical_proposition=original,
    )
    person = Parliamentarian.objects.create(full_name="Sâmia Bomfim")
    PropositionAuthor.objects.create(proposition=original, parliamentarian=person)
    institutional = InstitutionalAuthor.objects.create(
        name="Câmara dos Deputados", kind="instituição"
    )
    PropositionAuthor.objects.create(proposition=senate, institutional_author=institutional)
    event(original, "camara:1", 10, dispatch="Remessa ao Senado Federal")
    event(senate, "senado-informe:1", 9)
    cache.clear()

    from django.test import Client

    client = Client()
    explorer = client.get("/api/v1/activity/explorer", {"search": "2448/2022"}).json()
    assert explorer["total"] == 1
    assert explorer["items"][0]["id"] == original.pk
    assert explorer["items"][0]["current_house"] == "senado"
    assert explorer["items"][0]["celerity"]["movements_last_90_days"] == 2
    detail = client.get(
        "/api/v1/activity/by-number", {"house": "camara", "number_label": original.number_label}
    ).json()
    assert detail["id"] == original.pk
    assert detail["presented_at"] == original.presented_at.isoformat()
    assert detail["authors"][0]["name"] == "Sâmia Bomfim"
    assert detail["current_status"] == senate.current_status
    assert [entry["source_house"] for entry in detail["events"]] == ["senado", "camara"]
    assert [entry["url"] for entry in detail["events"]] == [
        senate.tramitation_url,
        original.tramitation_url,
    ]
    assert detail["celerity"]["movements_last_90_days"] == 2
    assert len(client.get("/api/v1/activity/").json()) == 1
    assert client.get("/api/v1/propositions/", {"q": "2448/2022"}).json()["count"] == 1
    assert client.get(f"/api/v1/propositions/{senate.pk}").status_code == 404
    assert (
        client.get(
            "/api/v1/activity/by-number", {"house": "senado", "number_label": original.number_label}
        ).status_code
        == 404
    )
    assert Proposition.objects.count() == 2  # both official sources retained


@pytest.mark.django_db
def test_transfer_requires_explicit_senate_origin_and_camara_remittance():
    process = {
        "siglaCasaIniciadora": "CD",
        "casaIdentificadora": "SF",
        "sigla": "PL",
        "numero": 2883,
        "ano": 2024,
        "outrosNumeros": [
            {
                "casaIdentificadora": "CD",
                "siglaEnteIdentificador": "CD",
                "sigla": "PL",
                "numero": "02883",
                "ano": 2024,
            }
        ],
    }
    identity = senate_origin(process)
    assert identity == {"type_code": "PL", "number": 2883, "year": 2024}
    assert senate_origin({**process, "siglaCasaIniciadora": "SF"}) is None
    assert senate_origin({**process, "outrosNumeros": process["outrosNumeros"] * 2}) is None
    assert senate_origin({**process, "numero": 999}) is None
    assert senate_origin({**process, "numero": "broken"}) is None

    senate = proposition(
        "senado",
        176022,
        2883,
        2024,
        originating_house="camara",
        raw_payload={"_house_transfer": identity},
    )
    original = proposition("camara", 2449135, 2883, 2024)
    assert link_senate_transfer(senate) is None  # label alone is not proof
    event(original, "camara:transfer", 10, dispatch="Remessa ao Senado Federal")
    assert link_senate_transfer(senate) == original
    assert link_senate_transfer(senate) == original
    senate.refresh_from_db()
    assert senate.canonical_proposition_id == original.pk


@pytest.mark.django_db
def test_ambiguous_camara_match_does_not_link():
    identity = {"type_code": "PL", "number": 2883, "year": 2024}
    senate = proposition(
        "senado",
        176022,
        2883,
        2024,
        originating_house="camara",
        raw_payload={"_house_transfer": identity},
    )
    for pk in (2449135, 2449136):
        original = proposition("camara", pk, 2883, 2024)
        event(original, f"camara:{pk}", 10, dispatch="Remessa ao Senado Federal")
    assert link_senate_transfer(senate) is None
    senate.refresh_from_db()
    assert senate.canonical_proposition_id is None


@pytest.mark.django_db
def test_senate_enactment_is_shown_under_original_identity():
    original = proposition("camara", 2335003, 2448, 2022)
    senate = proposition(
        "senado",
        176010,
        2448,
        2022,
        originating_house="camara",
        canonical_proposition=original,
        current_status_code=64,
        enacted_law_type="Lei",
        enacted_law_number=15123,
        enacted_law_year=2026,
        enacted_at=date(2026, 10, 25),
    )
    org = AssessmentOrganization.objects.create(name="AzMina")
    PropositionAnnotation.objects.create(
        proposition=original, organization=org, is_favorable=True, category="saude"
    )
    cache.clear()
    from django.test import Client

    response = Client().get("/api/v1/activity/enacted-projects").json()
    assert len(response) == 1
    assert response[0]["id"] == original.pk
    assert response[0]["current_house"] == "senado"
    assert response[0]["enactment"]["law_label"] == "Lei 15.123/2026"
    assert response[0]["enactment"]["status_code"] == 64
    assert Proposition.objects.get(pk=senate.pk).enacted_at == date(2026, 10, 25)


@pytest.mark.django_db
def test_historical_senate_delivery_suppresses_original_alert():
    original = proposition("camara", 2335003, 2448, 2022)
    senate = proposition(
        "senado", 176010, 2448, 2022, originating_house="camara", canonical_proposition=original
    )
    prior = Subscription.objects.create(
        email="leitora@example.com", frequency="daily", ast={}, query="casa_senado", is_active=True
    )
    current = Subscription.objects.create(
        email=prior.email, frequency="daily", ast={}, query="casa_camara", is_active=True
    )
    AlertDelivery.objects.create(subscription=prior, proposition=senate)
    send_alert_email(current.pk, original.pk)
    from apps.subscriptions.models import PendingAlert

    assert not PendingAlert.objects.exists()
    send_alert_email(current.pk, senate.pk)
    assert not PendingAlert.objects.exists()
    assert AlertDelivery.objects.count() == 1


@pytest.mark.django_db
def test_backfill_links_both_confirmed_pairs_without_touching_deliveries():
    records = []
    for number, year, camara_id, senate_id in (
        (2448, 2022, 2335003, 176010),
        (2883, 2024, 2449135, 176022),
    ):
        records.append(
            (
                proposition("camara", camara_id, number, year),
                proposition("senado", senate_id, number, year),
            )
        )
    sub = Subscription.objects.create(
        email="leitora@example.com", frequency="daily", ast={}, query="casa_senado", is_active=True
    )
    AlertDelivery.objects.create(subscription=sub, proposition=records[0][1])
    migration = import_module("apps.propositions.migrations.0016_cross_house_transfer")
    schema_editor = SimpleNamespace(connection=connection)
    migration.link_confirmed_transfers(apps, schema_editor)
    migration.link_confirmed_transfers(apps, schema_editor)
    for original, senate in records:
        senate.refresh_from_db()
        assert senate.canonical_proposition_id == original.pk
        assert senate.originating_house == "camara"
    assert list(AlertDelivery.objects.values_list("proposition_id", flat=True)) == [
        records[0][1].pk
    ]


@pytest.mark.django_db
def test_weekly_snapshot_uses_one_identity_and_both_houses_events():
    from apps.newsletters.report import build_snapshot

    original = proposition("camara", 2335003, 2448, 2022)
    senate = proposition(
        "senado", 176010, 2448, 2022, originating_house="camara", canonical_proposition=original
    )
    when = timezone.now() - timedelta(days=2)
    PropositionEvent.objects.create(
        proposition=senate,
        source_event_id="senado-informe:1",
        event_at=when,
        title="Aguardando deliberação",
        situation="Aguardando deliberação",
        raw_payload={"idSituacaoIniciada": 15},
    )
    snapshot = build_snapshot((when - timedelta(days=1)).date(), (when + timedelta(days=1)).date())
    assert len(snapshot) == 1
    assert snapshot[0]["id"] == original.pk
    assert snapshot[0]["url"] == senate.tramitation_url
    assert [entry["source_id"] for entry in snapshot[0]["week_events"]] == ["senado-informe:1"]


@pytest.mark.django_db
def test_origin_imported_after_receiving_house_links_on_retry():
    senate = proposition(
        "senado",
        176022,
        2883,
        2024,
        originating_house="camara",
        raw_payload={"_house_transfer": {"type_code": "PL", "number": 2883, "year": 2024}},
    )
    original = proposition("camara", 2449135, 2883, 2024)
    event(original, "camara:transfer", 10, dispatch="Remessa ao Senado Federal")
    assert link_pending_senate_transfers(original) == [senate]
    assert link_pending_senate_transfers(original) == []


@pytest.mark.django_db
@pytest.mark.parametrize("relevant", [True, False])
def test_ingestion_links_official_senate_process_and_avoids_a_new_public_bill(
    monkeypatch, relevant
):
    original = proposition("camara", 2335003, 2448, 2022)
    event(original, "camara:transfer", 10, dispatch="Remessa ao Senado Federal")
    process = {
        "id": 9115855,
        "codigoMateria": 176010,
        "sigla": "PL",
        "numero": 2448,
        "ano": 2022,
        "identificacao": "PL 2448/2022",
        "siglaCasaIniciadora": "CD",
        "casaIdentificadora": "SF",
        "outrosNumeros": [
            {
                "casaIdentificadora": "CD",
                "siglaEnteIdentificador": "CD",
                "sigla": "PL",
                "numero": "02448",
                "ano": 2022,
            }
        ],
        "documento": {"dataApresentacao": "2026-10-20", "resumoAutoria": "Câmara dos Deputados"},
        "conteudo": {"ementa": "Proteção das vítimas em estádios"},
        "situacaoAtual": "AGUARDANDO DESPACHO",
        "autuacoes": [
            {
                "informesLegislativos": [
                    {
                        "id": 2320542,
                        "data": "2026-10-21 08:48:33",
                        "descricao": "Autuado o PL 2448/2022, proveniente da Câmara dos Deputados.",
                    }
                ]
            }
        ],
    }
    run = IngestionRun.objects.create(
        house="senado",
        window_start=date(2026, 10, 20),
        window_end=date(2026, 10, 22),
    )
    item = IngestionItem.objects.create(
        run=run,
        external_id=176010,
        summary={
            "_process_summary": {
                "id": process["id"],
                "identificacao": "PL 2448/2022",
                "dataApresentacao": "2026-10-20",
                "ementa": process["conteudo"]["ementa"],
            },
            "IdentificacaoMateria": {"CodigoMateria": 176010, "IdentificacaoProcesso": 9115855},
        },
    )

    class Source:
        def fetch_process(self, process_id):
            assert process_id == 9115855
            return process

        def fetch_authors(self, materia_id):
            return [{"NomeAutor": "Câmara dos Deputados"}]

    monkeypatch.setattr(
        "apps.ingestion.sync._discovery_relevance",
        lambda *_: {"row_relevant": relevant, "temas": []},
    )
    monkeypatch.setattr("apps.ingestion.sync._documents", lambda *args, **kwargs: None)
    senate = sync_item(item, Source())
    assert senate.canonical_proposition_id == original.pk
    assert senate.originating_house == "camara"
    assert senate.raw_payload["_house_transfer"] == {
        "type_code": "PL",
        "number": 2448,
        "year": 2022,
    }
    assert not senate.is_approved
    assert senate.events.count() == 1
    assert sync_item(item, Source()).pk == senate.pk
    assert Proposition.objects.count() == 2
    assert senate.events.count() == 1
