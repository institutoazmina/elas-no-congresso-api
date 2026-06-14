from datetime import date

import pytest

from apps.core.enums import Gender, House
from apps.ingestion.resolvers import _is_institutional, resolve_author
from apps.legislatures.models import (
    InstitutionalAuthor,
    Legislature,
    Parliamentarian,
    ParliamentarianTerm,
    Party,
)


def _make_term(external_id: int, house: str = House.CAMARA) -> ParliamentarianTerm:
    leg, _ = Legislature.objects.get_or_create(
        number=57, defaults={"start_date": date(2023, 2, 1), "end_date": date(2027, 1, 31)}
    )
    party, _ = Party.objects.get_or_create(acronym="PT", defaults={"name": "Partido dos Trabalhadores"})
    parl = Parliamentarian.objects.create(full_name="Deputada Existente")
    ParliamentarianTerm.objects.create(
        parliamentarian=parl,
        legislature_number=leg,
        party=party,
        house=house,
        role="titular",
        state="SP",
        external_id=external_id,
        start_date=date(2023, 2, 1),
    )
    return parl


class TestIsInstitutional:
    def test_detects_hints(self):
        assert _is_institutional("Poder Executivo", "")
        assert _is_institutional("X", "Comissão de Justiça")
        assert not _is_institutional("Maria Silva", "Deputada")


@pytest.mark.django_db
class TestResolveAuthor:
    def test_empty_name_returns_none(self):
        assert resolve_author({"name": ""}, House.CAMARA) == (None, None)

    def test_institutional_creates_author(self):
        parl, inst = resolve_author(
            {"name": "Senado Federal - Comissão", "kind": "Órgão"}, House.CAMARA
        )
        assert parl is None
        assert isinstance(inst, InstitutionalAuthor)
        # idempotente
        _, inst2 = resolve_author({"name": "Senado Federal - Comissão", "kind": "Órgão"}, House.CAMARA)
        assert inst2.pk == inst.pk

    def test_resolves_existing_term_by_external_id(self):
        parl = _make_term(12345)
        got, inst = resolve_author({"name": "Qualquer Nome", "external_id": 12345}, House.CAMARA)
        assert inst is None
        assert got.pk == parl.pk

    def test_creates_minimal_when_unknown(self):
        parl, inst = resolve_author({"name": "Pessoa Nova", "external_id": 999999}, House.CAMARA)
        assert inst is None
        assert parl.full_name == "Pessoa Nova"
        # segunda vez reaproveita (get_or_create)
        parl2, _ = resolve_author({"name": "Pessoa Nova"}, House.CAMARA)
        assert parl2.pk == parl.pk

    def test_creates_with_gender(self):
        parl, _ = resolve_author({"name": "Nova Com Sexo", "gender": Gender.F}, House.CAMARA)
        assert parl.gender == Gender.F

    def test_backfills_gender_on_existing(self):
        parl = _make_term(54321)
        assert not parl.gender
        resolve_author({"name": "Ignora", "external_id": 54321, "gender": Gender.M}, House.CAMARA)
        parl.refresh_from_db()
        assert parl.gender == Gender.M
