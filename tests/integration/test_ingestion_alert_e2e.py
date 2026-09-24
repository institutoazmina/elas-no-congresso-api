"""Fluxo completo: Câmara → preparação para análise → categoria → alerta diário."""

import pytest

from apps.core.enums import PropositionCategory
from apps.ingestion import tasks as ingestion_tasks
from apps.ingestion.models import IngestionRun
from apps.propositions.models import AssessmentOrganization, Proposition, PropositionAnnotation
from apps.subscriptions.models import AlertDelivery, Subscription
from apps.subscriptions.service import register_subscriptions


class _CamaraComUmaProposicao:
    """Dublê da API da Câmara, mantendo o restante do pipeline real."""

    summary = {
        "id": 990001,
        "siglaTipo": "PL",
        "numero": 42,
        "ano": 2026,
        "ementa": "Institui medidas de proteção contra violência contra a mulher.",
    }
    detail = {
        **summary,
        "dataApresentacao": "2026-09-24",
        "ementaDetalhada": summary["ementa"],
        "keywords": "violência contra a mulher",
        "urlInteiroTeor": "https://camara.example.test/pl-42.pdf",
        "statusProposicao": {
            "dataHora": "2026-09-24T10:00:00",
            "sequencia": 1,
            "descricaoTramitacao": "Apresentação",
            "descricaoSituacao": "Em tramitação",
        },
    }

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def list_propositions(self, start, end):
        yield self.summary

    def fetch_detail(self, proposition_id):
        assert proposition_id == self.summary["id"]
        return self.detail

    def fetch_authors(self, proposition_id):
        assert proposition_id == self.summary["id"]
        return []


def _activate_daily_subscription(email: str, ast: dict) -> int:
    subscription_id = register_subscriptions(
        email,
        [{"frequency": "daily", "ast": ast}],
    )[0]
    Subscription.objects.filter(pk=subscription_id).update(is_active=True)
    return subscription_id


@pytest.mark.django_db(transaction=True)
def test_ingestao_e_categorizacao_entregam_alerta_do_filtro_do_site(monkeypatch, outbox):
    """Somente os filtros de categoria do modal recebem a PL categorizada."""
    no_match_educacao = _activate_daily_subscription(
        "educacao-e2e@example.com",
        {"field": "categoria", "op": "in", "value": ["educacao_cultura"]},
    )
    match_exclusivo = _activate_daily_subscription(
        "saude-e2e@example.com",
        {"field": "categoria", "op": "in", "value": ["saude"]},
    )
    match_multicategoria = _activate_daily_subscription(
        "multicategoria-e2e@example.com",
        {
            "field": "categoria",
            "op": "in",
            "value": ["educacao_cultura", "saude"],
        },
    )

    monkeypatch.setattr(
        ingestion_tasks,
        "CamaraClient",
        lambda: _CamaraComUmaProposicao(),
    )
    monkeypatch.setattr(
        "apps.ingestion.fulltext.extract_pdf_text",
        lambda url: "Inteiro teor preparado para a análise da IA.",
    )

    run = IngestionRun.objects.get(pk=ingestion_tasks.ingest_camara())
    proposition = Proposition.objects.get(house="camara", external_id=990001)

    assert run.status == IngestionRun.Status.SUCCESS
    assert run.upserted_count == 1
    assert proposition.full_text == "Inteiro teor preparado para a análise da IA."
    assert outbox == []

    # O caso de borda do modal: acompanha uma categoria, mas só uma PL já
    # conhecida. A categorização chega depois de a pessoa ter se inscrito.
    match_proposicao_especifica = _activate_daily_subscription(
        "proposicao-especifica-e2e@example.com",
        {
            "op": "AND",
            "children": [
                {"field": "categoria", "op": "in", "value": ["saude"]},
                {"field": "proposicao", "op": "in", "value": [proposition.pk]},
            ],
        },
    )

    organization = AssessmentOrganization.objects.create(name="Análise E2E")
    annotation = PropositionAnnotation.objects.create(
        proposition=proposition,
        organization=organization,
        category=PropositionCategory.SAUDE,
    )

    delivered_subscriptions = set(
        AlertDelivery.objects.filter(proposition=proposition).values_list("subscription_id", flat=True)
    )
    assert delivered_subscriptions == {
        match_exclusivo,
        match_multicategoria,
        match_proposicao_especifica,
    }
    assert no_match_educacao not in delivered_subscriptions
    assert {message.to[0] for message in outbox} == {
        "saude-e2e@example.com",
        "multicategoria-e2e@example.com",
        "proposicao-especifica-e2e@example.com",
    }
    assert all(proposition.number_label in message.alternatives[0][0] for message in outbox)

    annotation.comments = "Anotação revisada sem mudar a categoria."
    annotation.save(update_fields=["comments"])

    assert len(outbox) == 3
    assert AlertDelivery.objects.filter(proposition=proposition).count() == 3
