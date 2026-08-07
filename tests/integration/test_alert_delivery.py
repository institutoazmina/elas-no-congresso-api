"""Quem recebe o quê, e quando.

Diário = e-mail assim que a proposição entra. Semanal = um resumo só, no dia
do envio da newsletter. As duas rotas leem a mesma tabela, então o risco real
é uma vazar na outra.
"""
import datetime

import pytest

from apps.legislatures.models import Parliamentarian
from apps.propositions.models import (
    AssessmentOrganization,
    Proposition,
    PropositionAnnotation,
    PropositionRapporteur,
)
from apps.subscriptions.models import Subscription
from apps.subscriptions.tasks import match_and_notify, send_weekly_digest


def _make_annotation(proposition, **kwargs):
    org, _ = AssessmentOrganization.objects.get_or_create(name="Anis")
    return PropositionAnnotation.objects.create(
        proposition=proposition, organization=org, **kwargs
    )


def _make_parlamentar(**kwargs):
    defaults = {"full_name": "Maria Silva", "gender": "F"}
    defaults.update(kwargs)
    return Parliamentarian.objects.create(**defaults)


def _make_proposition(**kwargs):
    defaults = {
        "house": "camara",
        "external_id": 1,
        "type_code": "pl",
        "number_label": "PL 1/2024",
        "number": 1,
        "year": 2024,
        "presented_at": datetime.date(2024, 1, 1),
        "ementa": "Ementa de teste",
        "current_status": "Em tramitação",
    }
    defaults.update(kwargs)
    return Proposition.objects.create(**defaults)


def _make_subscription(**kwargs):
    defaults = {
        "email": "leitora@example.com",
        "ast": {},
        "query": "casa_camara",
        "frequency": "daily",
        "is_active": True,
    }
    defaults.update(kwargs)
    return Subscription.objects.create(**defaults)


# transaction=True: o disparo do alerta acontece no on_commit, que não roda
# quando o teste segura tudo numa transação revertida no fim.
@pytest.mark.django_db(transaction=True)
class TestAlertaImediato:
    def test_inscricao_diaria_recebe_assim_que_a_proposicao_entra(self, outbox):
        _make_subscription(frequency="daily")

        _make_proposition(external_id=200)  # o post_save já enfileira o match

        assert [m.to for m in outbox] == [["leitora@example.com"]]

    def test_inscricao_semanal_nao_recebe_alerta_imediato(self, outbox):
        _make_subscription(frequency="weekly")

        _make_proposition(external_id=201)

        assert outbox == []

    def test_filtro_por_proposicao_so_alerta_daquela(self, outbox):
        acompanhada = _make_proposition(external_id=210, number_label="PL 7/2024")
        outra = _make_proposition(external_id=211, number_label="PL 8/2024")
        _make_subscription(frequency="daily", query=f"proposicao_{acompanhada.pk}")

        match_and_notify.delay(outra.pk)
        assert outbox == []

        match_and_notify.delay(acompanhada.pk)
        assert [m.to for m in outbox] == [["leitora@example.com"]]

    def test_alerta_sai_quando_a_anotacao_chega(self, outbox):
        """A categoria vem da avaliação humana, dias depois da coleta — se o
        alerta só olhasse o post_save da proposição, nunca casaria."""
        _make_subscription(frequency="daily", query="categoria_violencias_de_genero")
        prop = _make_proposition(external_id=240)
        assert outbox == []

        _make_annotation(prop, category="violencias_de_genero")

        assert [m.to for m in outbox] == [["leitora@example.com"]]

    def test_mesma_proposicao_nao_avisa_duas_vezes(self, outbox):
        _make_subscription(frequency="daily", query="casa_camara")
        prop = _make_proposition(external_id=241)
        assert len(outbox) == 1

        _make_annotation(prop, category="saude")
        match_and_notify.delay(prop.pk)

        assert len(outbox) == 1

    def test_categoria_de_fora_da_inscricao_nao_alerta(self, outbox):
        """As leitoras escolhem "Categorias 2026", não as palavras-chave do raspador."""
        _make_subscription(frequency="daily", query="categoria_violencias_de_genero")

        _make_annotation(_make_proposition(external_id=231), category="saude")

        assert outbox == []

    def test_filtro_por_relator_alerta_quando_ele_relata(self, outbox):
        relator = _make_parlamentar()
        _make_subscription(frequency="daily", query=f"relator_{relator.pk}")

        prop = _make_proposition(external_id=220)
        PropositionRapporteur.objects.create(
            proposition=prop, parliamentarian=relator, designated_at=datetime.date(2024, 2, 1)
        )
        match_and_notify.delay(prop.pk)

        assert [m.to for m in outbox] == [["leitora@example.com"]]


@pytest.mark.django_db(transaction=True)
class TestDigestSemanal:
    def test_junta_a_semana_num_email_so(self, outbox):
        _make_subscription(frequency="weekly")
        _make_proposition(external_id=300, number_label="PL 10/2024")
        _make_proposition(external_id=301, number_label="PL 11/2024")

        send_weekly_digest.delay()

        assert len(outbox) == 1
        assert "PL 10/2024" in outbox[0].body
        assert "PL 11/2024" in outbox[0].body

    def test_semana_sem_novidade_nao_gera_email(self, outbox):
        _make_subscription(frequency="weekly")

        send_weekly_digest.delay()

        assert outbox == []
