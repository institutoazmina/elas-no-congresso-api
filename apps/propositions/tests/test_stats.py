"""Cenário mínimo que exercita as três regras de contagem dos endpoints BFF:
dedupe de anotações, atribuição a todos os coautores e janela da legislatura."""

from datetime import date

import pytest

from apps.core.enums import Gender, House, PropositionCategory
from apps.legislatures.models import (
    Legislature,
    Parliamentarian,
    ParliamentarianTerm,
    Party,
)
from apps.propositions.models import (
    AssessmentOrganization,
    Proposition,
    PropositionAnnotation,
    PropositionAuthor,
)

pytestmark = pytest.mark.django_db

BASE = "/api/v1/stats/propositions"


def _proposition(number: int, presented_at: date) -> Proposition:
    return Proposition.objects.create(
        house=House.CAMARA,
        external_id=number,
        type_code="PL",
        number_label=f"PL {number}",
        number=number,
        year=presented_at.year,
        presented_at=presented_at,
        ementa=f"Ementa {number}",
    )


@pytest.fixture
def scenario():
    """Ana (F/PT/SP) e Beto (M/PL/RJ), três proposições, quatro anotações.

    - prop1 (56ª leg): coautoria Ana+Beto, DUAS anotações desfavoráveis de
      organizações diferentes → tem de contar 1, não 2.
    - prop2 (56ª leg): só Ana, favorável.
    - prop3 (57ª leg): só Beto, desfavorável.
    """
    Legislature.objects.create(
        number=56, start_date=date(2019, 2, 1), end_date=date(2023, 1, 31)
    )
    Legislature.objects.create(
        number=57, start_date=date(2023, 2, 1), end_date=date(2027, 1, 31)
    )
    pt = Party.objects.create(acronym="PT", name="Partido dos Trabalhadores")
    pl = Party.objects.create(acronym="PL", name="Partido Liberal")
    ana = Parliamentarian.objects.create(full_name="Ana", gender=Gender.F)
    beto = Parliamentarian.objects.create(full_name="Beto", gender=Gender.M)
    for parl, party, state, ext in ((ana, pt, "SP", 1), (beto, pl, "RJ", 2)):
        ParliamentarianTerm.objects.create(
            parliamentarian=parl,
            legislature_number_id=56,
            party=party,
            house=House.CAMARA,
            role="deputado",
            state=state,
            external_id=ext,
            start_date=date(2019, 2, 1),
        )

    azmina = AssessmentOrganization.objects.create(name="AzMina")
    outra = AssessmentOrganization.objects.create(name="Outra ONG")

    prop1 = _proposition(1, date(2020, 5, 1))
    PropositionAuthor.objects.create(
        proposition=prop1, parliamentarian=ana, party=pt,
        state_at_authorship="SP", order_index=1,
    )
    PropositionAuthor.objects.create(
        proposition=prop1, parliamentarian=beto, party=pl,
        state_at_authorship="RJ", order_index=2,
    )
    for org in (azmina, outra):
        PropositionAnnotation.objects.create(
            proposition=prop1, organization=org, is_favorable=False,
            category=PropositionCategory.VIOLENCIAS_DE_GENERO,
        )

    prop2 = _proposition(2, date(2021, 6, 1))
    PropositionAuthor.objects.create(
        proposition=prop2, parliamentarian=ana, party=pt,
        state_at_authorship="SP", order_index=1,
    )
    PropositionAnnotation.objects.create(
        proposition=prop2, organization=azmina, is_favorable=True,
        category=PropositionCategory.SAUDE,
    )

    prop3 = _proposition(3, date(2024, 3, 1))
    PropositionAuthor.objects.create(
        proposition=prop3, parliamentarian=beto, party=pl,
        state_at_authorship="RJ", order_index=1,
    )
    PropositionAnnotation.objects.create(
        proposition=prop3, organization=azmina, is_favorable=False,
        category=PropositionCategory.SAUDE,
    )


def test_by_legislature(client, scenario):
    body = client.get(f"{BASE}/legislatures").json()
    assert body["legislatures"] == [
        {"number": 56, "from": 2019, "to": 2023, "label": "56ª Legislatura", "unfavorable": 1},
        {"number": 57, "from": 2023, "to": 2027, "label": "57ª Legislatura", "unfavorable": 1},
    ]


def test_by_category(client, scenario):
    body = client.get(f"{BASE}/categories").json()
    # prop2 é favorável → categoria 'saude' só aparece por causa da prop3
    assert body["categories"] == [
        {"value": "saude", "label": "Saúde", "unfavorable": 1},
        {"value": "violencias_de_genero", "label": "Violências de Gênero", "unfavorable": 1},
    ]


def test_by_gender(client, scenario):
    body = client.get(f"{BASE}/genders").json()
    # Ana: prop1 desfavorável + prop2 favorável; Beto: prop1 e prop3 desfavoráveis
    assert body == {
        "women": {"favorable": 0.5, "unfavorable": 0.5},
        "men": {"favorable": 0.0, "unfavorable": 1.0},
    }


def test_by_party_ranks_by_stance(client, scenario):
    unfavorable = client.get(f"{BASE}/parties").json()["parties"]
    assert unfavorable == [
        {"label": "PL", "favorable": 0, "unfavorable": 2},
        {"label": "PT", "favorable": 1, "unfavorable": 1},
    ]
    favorable = client.get(f"{BASE}/parties?stance=favorable&limit=1").json()["parties"]
    assert favorable == [{"label": "PT", "favorable": 1, "unfavorable": 1}]


def test_by_state(client, scenario):
    assert client.get(f"{BASE}/states").json()["states"] == [
        {"label": "RJ", "favorable": 0, "unfavorable": 2},
        {"label": "SP", "favorable": 1, "unfavorable": 1},
    ]
