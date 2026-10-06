"""House filters used by the daily-alert form, from search to delivery."""

import pytest
from django.core.cache import cache

from apps.ingestion import tasks as ingestion_tasks
from apps.ingestion.models import IngestionRun
from apps.propositions.models import (
    AssessmentOrganization,
    Proposition,
    PropositionAnnotation,
)
from apps.subscriptions.models import Subscription
from apps.subscriptions.service import match_proposition
from apps.subscriptions.tasks import match_and_notify, send_daily_digest


@pytest.fixture(autouse=True)
def clear_cache():
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def propositions(db):
    organization = AssessmentOrganization.objects.create(name="House filter assessment")
    result = []
    for house in ("camara", "senado"):
        for number, category in ((10, "educacao_cultura"), (11, "educacao_cultura"), (12, "saude")):
            proposition = Proposition.objects.create(
                house=house,
                external_id=number,
                type_code="pl",
                number_label=f"PL {number}/2026",
                number=number,
                year=2026,
                presented_at="2026-01-01",
                ementa="Educação e cultura para mulheres"
                if category == "educacao_cultura"
                else "Direitos das mulheres",
                current_status="Em tramitação",
                is_approved=True,
            )
            PropositionAnnotation.objects.create(
                proposition=proposition, organization=organization, category=category
            )
            result.append(proposition)
    return result


@pytest.mark.django_db
@pytest.mark.parametrize(
    "house", ["camara", "senado", None, ""], ids=["camara", "senado", "both", "empty"]
)
@pytest.mark.parametrize("query", ["PL 10/2026", "Educação"])
def test_proposition_search_filters_by_house(client, propositions, house, query):
    params = {"q": query, "limit": 8}
    if house is not None:
        params["house"] = house

    response = client.get("/api/v1/propositions/", params)

    assert response.status_code == 200
    expected = {
        proposition.pk
        for proposition in propositions
        if (not house or proposition.house == house)
        and (proposition.number == 10 if query.startswith("PL") else proposition.number in (10, 11))
    }
    data = response.json()
    assert {item["id"] for item in data["items"]} == expected
    assert data["count"] == len(expected)
    if house:
        assert {item["house"] for item in data["items"]} == {house}


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("house", ["camara", "senado", None], ids=["camara", "senado", "both"])
@pytest.mark.parametrize(
    "specific_propositions",
    [False, True],
    ids=["all-propositions", "specific-propositions"],
)
def test_daily_subscription_house_filter_matches_and_delivers(
    client, outbox, propositions, house, specific_propositions, settings, daily_clock
):
    settings.QUITERIA_ENABLED = False
    selected_ids = [proposition.pk for proposition in propositions if proposition.number == 10]
    filters = [{"field": "categoria", "op": "in", "value": ["educacao_cultura"]}]
    if house:
        filters.append({"field": "casa", "op": "eq", "value": house})
    if specific_propositions:
        filters.append({"field": "proposicao", "op": "in", "value": selected_ids})
    ast = filters[0] if len(filters) == 1 else {"op": "AND", "children": filters}

    response = client.post(
        "/api/v1/subscriptions/",
        data={
            "email": "house-filter@example.com",
            "accepted_terms": True,
            "alerts": [{"frequency": "daily", "ast": ast}],
        },
        content_type="application/json",
    )

    assert response.status_code == 201
    subscription = Subscription.objects.get(email="house-filter@example.com")
    assert subscription.frequency == "daily"
    assert subscription.ast == ast
    assert not subscription.is_active
    assert (f"casa_{house}" in subscription.query) if house else ("casa_" not in subscription.query)
    assert len(outbox) == 1

    confirmation = client.get(f"/api/v1/subscriptions/confirm/{subscription.confirm_token}")
    assert confirmation.status_code == 302
    subscription.refresh_from_db()
    assert subscription.is_active
    outbox.clear()

    expected = {
        proposition.pk
        for proposition in propositions
        if proposition.number in (10, 11)
        and (not house or proposition.house == house)
        and (not specific_propositions or proposition.pk in selected_ids)
    }
    for proposition in propositions:
        matched = match_proposition(proposition.pk, frequency="daily")
        assert matched == ([subscription.pk] if proposition.pk in expected else [])
        match_and_notify.delay(proposition.pk)

    assert outbox == []
    daily_clock.now = daily_clock.now.replace(hour=9)
    send_daily_digest()
    assert set(subscription.deliveries.values_list("proposition_id", flat=True)) == expected
    assert len(outbox) == 1
    assert all(message.to == [subscription.email] for message in outbox)


class LegislativeFeed:
    """Deterministic legislative API inputs; ingestion and delivery remain real."""

    ementa = "Institui medidas de educação e cultura para a mulher."

    def __init__(self, house):
        self.house = house

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def list_propositions(self, start, end):
        yield {
            "id": 990001,
            "siglaTipo": "PL",
            "numero": 42,
            "ano": 2026,
            "ementa": self.ementa,
        }

    def list_materias(self, day):
        yield {
            "IdentificacaoMateria": {
                "CodigoMateria": 990001,
                "SiglaSubtipoMateria": "PL",
                "NumeroMateria": 42,
                "AnoMateria": 2026,
            },
            "Ementa": self.ementa,
            "DataApresentacao": "2026-10-05",
        }

    def fetch_detail(self, external_id):
        assert external_id == 990001
        if self.house == "camara":
            return {
                "dataApresentacao": "2026-10-05",
                "ementaDetalhada": self.ementa,
                "keywords": "mulher",
                "statusProposicao": {
                    "dataHora": "2026-10-05T10:00:00",
                    "sequencia": 1,
                    "descricaoTramitacao": "Apresentação",
                    "descricaoSituacao": "Em tramitação",
                },
            }
        return {
            "DadosBasicosMateria": {
                "DataApresentacao": "2026-10-05",
                "EmentaMateria": self.ementa,
            }
        }

    def fetch_authors(self, external_id):
        return []

    def fetch_texts(self, external_id):
        return []

    def fetch_movements(self, external_id):
        return {}


@pytest.mark.django_db(transaction=True)
def test_api_flow_smoke_without_ai(client, outbox, settings, monkeypatch, daily_clock):
    """Signup → confirmation → ingestion → review → alerts → unsubscribe."""
    settings.QUITERIA_ENABLED = False
    subscriptions = {}
    for house in ("senado", "camara", None):
        category = {"op": "in", "field": "categoria", "value": ["educacao_cultura"]}
        ast = (
            {
                "op": "AND",
                "children": [
                    category,
                    {"op": "eq", "field": "casa", "value": house},
                ],
            }
            if house
            else category
        )
        response = client.post(
            "/api/v1/subscriptions/",
            data={
                "email": f"smoke-{house or 'both'}@example.com",
                "accepted_terms": True,
                "alerts": [{"frequency": "daily", "ast": ast}],
            },
            content_type="application/json",
        )
        assert response.status_code == 201
        subscription = Subscription.objects.get(email=f"smoke-{house or 'both'}@example.com")
        assert subscription.ast == ast
        assert not subscription.is_active
        subscriptions[house] = subscription
    assert len(outbox) == 3
    assert all("Confirmar inscrição" in message.alternatives[0][0] for message in outbox)

    monkeypatch.setattr(ingestion_tasks, "CamaraClient", lambda: LegislativeFeed("camara"))
    monkeypatch.setattr(ingestion_tasks, "SenadoClient", lambda: LegislativeFeed("senado"))
    for ingest in (ingestion_tasks.ingest_camara, ingestion_tasks.ingest_senado):
        run = IngestionRun.objects.get(pk=ingest())
        assert run.status == IngestionRun.Status.SUCCESS
        assert run.fetched_count == run.relevant_count == run.upserted_count == 1
        assert run.error_count == 0

    propositions = list(Proposition.objects.filter(external_id=990001))
    assert {proposition.house for proposition in propositions} == {"camara", "senado"}
    assert all(not proposition.is_approved for proposition in propositions)
    assert all(not hasattr(proposition, "analysis") for proposition in propositions)
    assert client.get("/api/v1/propositions/").json()["count"] == 0
    assert len(outbox) == 3

    for subscription in subscriptions.values():
        response = client.get(f"/api/v1/subscriptions/confirm/{subscription.confirm_token}")
        assert response.status_code == 302
        subscription.refresh_from_db()
        assert subscription.is_active
    outbox.clear()

    organization = AssessmentOrganization.objects.create(name="Smoke assessment")
    for proposition in propositions:
        PropositionAnnotation.objects.create(
            proposition=proposition, organization=organization, category="educacao_cultura"
        )
        assert not proposition.alert_deliveries.exists()
        proposition.is_approved = True
        proposition.save(update_fields=["is_approved"])
        assert not proposition.alert_deliveries.exists()
        assert (
            client.get("/api/v1/propositions/", {"house": proposition.house}).json()["count"] == 1
        )

    assert outbox == []
    daily_clock.now = daily_clock.now.replace(hour=9)
    send_daily_digest()
    for proposition in propositions:
        assert set(proposition.alert_deliveries.values_list("subscription_id", flat=True)) == {
            subscriptions[proposition.house].pk,
            subscriptions[None].pk,
        }
    assert len(outbox) == 3
    for house, subscription in subscriptions.items():
        messages = [message for message in outbox if message.to == [subscription.email]]
        assert len(messages) == 1
        assert all("PL 42/2026" in message.alternatives[0][0] for message in messages)
        if house:
            assert f"Casa: {house}" in messages[0].body

    for proposition in propositions:
        match_and_notify.delay(proposition.pk)
    assert len(outbox) == 3

    for subscription in subscriptions.values():
        response = client.get(f"/api/v1/subscriptions/unsubscribe/{subscription.unsubscribe_token}")
        assert response.status_code == 302
        subscription.refresh_from_db()
        assert not subscription.is_active
    for proposition in propositions:
        assert match_proposition(proposition.pk, frequency="daily") == []
        match_and_notify.delay(proposition.pk)
    assert len(outbox) == 3
