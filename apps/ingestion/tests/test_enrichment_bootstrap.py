from datetime import timedelta
from types import SimpleNamespace

import httpx
import pytest
from django.test import Client
from django.utils import timezone

from apps.ingestion import tasks
from apps.ingestion.clients.camara import CamaraClient
from apps.ingestion.clients.senado import SenadoClient
from apps.legislatures.models import (
    Legislature,
    Parliamentarian,
    ParliamentarianProfileSource,
    ParliamentarianTerm,
    Party,
)


def _client_for(cls, handler):
    inner = httpx.Client(transport=httpx.MockTransport(handler), base_url=cls.base_url)
    return cls(client=inner)


def test_camara_current_members_parses_singletons_and_paginates():
    def handler(request):
        if "pagina=2" in str(request.url):
            return httpx.Response(200, json={"dados": {"id": 2}, "links": []})
        return httpx.Response(
            200,
            json={
                "dados": {"id": 1},
                "links": [
                    {
                        "rel": "next",
                        "href": f"{CamaraClient.base_url}/deputados?pagina=2",
                    }
                ],
            },
        )

    client = _client_for(CamaraClient, handler)

    assert list(client.list_current_members()) == [{"id": 1}, {"id": 2}]


def test_senado_current_members_parses_singleton_and_list_payloads():
    payloads = iter(
        [
            {
                "ListaParlamentarEmExercicio": {
                    "Parlamentares": {"Parlamentar": {"id": 1}}
                }
            },
            {
                "ListaParlamentarEmExercicio": {
                    "Parlamentares": {"Parlamentar": [{"id": 2}, {"id": 3}]}
                }
            },
        ]
    )
    client = _client_for(SenadoClient, lambda request: httpx.Response(200, json=next(payloads)))

    assert client.list_current_members() == [{"id": 1}]
    assert client.list_current_members() == [{"id": 2}, {"id": 3}]


def _current_legislature():
    today = timezone.localdate()
    legislature, _ = Legislature.objects.get_or_create(
        number=57,
        defaults={"start_date": today - timedelta(days=100), "end_date": today + timedelta(days=100)},
    )
    return legislature


class _BootstrapClient:
    base_url = "https://official.example"

    def __init__(self, members, profiles, failure=None):
        self.members = members
        self.profiles = profiles
        self.failure = failure
        self.requested = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def list_current_members(self):
        if self.failure:
            raise self.failure
        return self.members

    def fetch_profile(self, external_id):
        self.requested.append(external_id)
        return self.profiles[external_id]


def _camara_member(external_id=101, name="Ana Pública", party="PT", state="SP"):
    return {
        "id": external_id,
        "nome": name,
        "siglaPartido": party,
        "siglaUf": state,
        "idLegislatura": 57,
    }


def _camara_profile(external_id=101, full_name="Ana Pública Civil"):
    return {
        "id": external_id,
        "nomeCivil": full_name,
        "ultimoStatus": {"nome": "Ana Pública"},
    }


def _camara_profile_named(external_id, name):
    return {
        "id": external_id,
        "nomeCivil": name,
        "ultimoStatus": {"nome": name},
    }


def _senado_member(
    external_id="202", public_name="Bruna Pública", full_name="Bruna Pública Civil"
):
    return {
        "IdentificacaoParlamentar": {
            "CodigoParlamentar": external_id,
            "NomeParlamentar": public_name,
            "NomeCompletoParlamentar": full_name,
            "SiglaPartidoParlamentar": "MDB",
            "UfParlamentar": "RJ",
        },
        "Mandato": {"DescricaoParticipacao": "Titular"},
    }


def _senado_profile(external_id=202, public_name="Bruna Pública", full_name="Bruna Pública Civil"):
    return {
        "IdentificacaoParlamentar": {
            "CodigoParlamentar": str(external_id),
            "NomeParlamentar": public_name,
            "NomeCompletoParlamentar": full_name,
        }
    }


def _prepare_task(monkeypatch, camara, senado, *, camara_minimum=1, senado_minimum=1):
    monkeypatch.setitem(tasks._EXPECTED_CURRENT_ROSTER, "camara", camara_minimum)
    monkeypatch.setitem(tasks._EXPECTED_CURRENT_ROSTER, "senado", senado_minimum)
    monkeypatch.setattr(tasks, "CamaraClient", lambda: camara)
    monkeypatch.setattr(tasks, "SenadoClient", lambda: senado)
    monkeypatch.setattr(tasks, "_load_tse_index", lambda: ({}, 0))
    monkeypatch.setattr(
        tasks,
        "_load_senado_front_snapshot",
        lambda: SimpleNamespace(fronts=(), failed_fronts=0),
    )
    monkeypatch.setattr(tasks, "persist_official_relationships", lambda **kwargs: None)


@pytest.mark.django_db
def test_enrichment_bootstraps_empty_terms_and_enriches_profiles(monkeypatch):
    legislature = _current_legislature()
    camara_person = Parliamentarian.objects.create(
        full_name="Ana Beatriz da Silva", social_name="Ana Publica"
    )
    senado_person = Parliamentarian.objects.create(
        full_name="Bruna Pública Civil", social_name="Bruna Pública"
    )
    camara = _BootstrapClient([_camara_member()], {101: _camara_profile()})
    senado = _BootstrapClient([_senado_member()], {202: _senado_profile()})
    _prepare_task(monkeypatch, camara, senado)

    result = tasks.enrich_parliamentarian_profiles()

    assert result["processed"] == 2
    assert result["failed"] == 0
    assert result["terms"]["members"] == 2
    assert Parliamentarian.objects.count() == 4
    assert ParliamentarianTerm.objects.count() == 2
    assert not ParliamentarianTerm.objects.filter(parliamentarian=camara_person).exists()
    assert not ParliamentarianTerm.objects.filter(parliamentarian=senado_person).exists()
    assert ParliamentarianTerm.objects.filter(
        house="camara",
        external_id=101,
        legislature_number=legislature,
        start_date=legislature.start_date,
        end_date=None,
        party__acronym="PT",
        state="SP",
    ).exists()
    assert ParliamentarianTerm.objects.filter(
        house="senado",
        external_id=202,
        legislature_number=legislature,
        party__acronym="MDB",
        state="RJ",
    ).exists()
    assert camara.requested == [101]
    assert senado.requested == [202]


@pytest.mark.django_db
def test_enrichment_bootstrap_is_idempotent_on_rerun(monkeypatch):
    _current_legislature()
    camara = _BootstrapClient([_camara_member()], {101: _camara_profile()})
    senado = _BootstrapClient([], {})
    _prepare_task(monkeypatch, camara, senado)

    first = tasks.enrich_parliamentarian_profiles()
    second = tasks.enrich_parliamentarian_profiles()

    assert first["terms"]["members"] == 1
    assert second["terms"]["members"] == 1
    assert Parliamentarian.objects.count() == 1
    assert ParliamentarianTerm.objects.count() == 1
    assert Party.objects.count() == 1


@pytest.mark.django_db
def test_ambiguous_name_creates_distinct_parliamentarian(monkeypatch):
    _current_legislature()
    first = Parliamentarian.objects.create(full_name="José da Silva")
    second = Parliamentarian.objects.create(full_name="JOSE DA SILVA")
    camara = _BootstrapClient(
        [_camara_member(name="Jose da Silva")], {101: _camara_profile(full_name="José Civil")}
    )
    _prepare_task(monkeypatch, camara, _BootstrapClient([], {}))

    tasks.enrich_parliamentarian_profiles()

    assert Parliamentarian.objects.count() == 3
    assert not ParliamentarianTerm.objects.filter(parliamentarian=first).exists()
    assert not ParliamentarianTerm.objects.filter(parliamentarian=second).exists()
    assert ParliamentarianTerm.objects.get().parliamentarian_id not in {first.pk, second.pk}


@pytest.mark.django_db
def test_profile_source_identity_precedes_name(monkeypatch):
    _current_legislature()
    existing = Parliamentarian.objects.create(full_name="Pessoa Fonte")
    ParliamentarianProfileSource.objects.create(
        parliamentarian=existing,
        source="camara",
        source_key="123",
        profile_values={},
    )
    camara = _BootstrapClient(
        [_camara_member(external_id=123, name="Nome não confiável")],
        {123: _camara_profile_named(123, "Nome não confiável")},
    )
    _prepare_task(monkeypatch, camara, _BootstrapClient([], {}))

    tasks.enrich_parliamentarian_profiles()

    assert Parliamentarian.objects.count() == 1
    assert ParliamentarianTerm.objects.get().parliamentarian_id == existing.pk


@pytest.mark.django_db
def test_ambiguous_historical_term_evidence_does_not_create_current_term(monkeypatch):
    _current_legislature()
    previous, _ = Legislature.objects.get_or_create(
        number=56,
        defaults={
            "start_date": timezone.localdate() - timedelta(days=1500),
            "end_date": timezone.localdate() - timedelta(days=500),
        },
    )
    previous_other, _ = Legislature.objects.get_or_create(
        number=55,
        defaults={
            "start_date": timezone.localdate() - timedelta(days=3000),
            "end_date": timezone.localdate() - timedelta(days=1600),
        },
    )
    first = Parliamentarian.objects.create(full_name="Primeira evidência")
    second = Parliamentarian.objects.create(full_name="Segunda evidência")
    first_party = Party.objects.create(acronym="P1", name="P1")
    second_party = Party.objects.create(acronym="P2", name="P2")
    for person, old_leg, party in (
        (first, previous, first_party),
        (second, previous_other, second_party),
    ):
        ParliamentarianTerm.objects.create(
            parliamentarian=person,
            legislature_number=old_leg,
            party=party,
            house="camara",
            role="Deputado",
            state="SP",
            external_id=777,
            start_date=old_leg.start_date,
            end_date=old_leg.end_date,
        )
    camara = _BootstrapClient(
        [_camara_member(external_id=777, name="Nome qualquer")],
        {777: _camara_profile_named(777, "Nome qualquer")},
    )
    _prepare_task(monkeypatch, camara, _BootstrapClient([], {}))

    result = tasks.enrich_parliamentarian_profiles()

    assert result["terms"]["failed"] >= 1
    assert not ParliamentarianTerm.objects.filter(
        house="camara", external_id=777, legislature_number__number=57
    ).exists()
    assert Parliamentarian.objects.count() == 2


@pytest.mark.django_db
def test_term_and_profile_source_disagreement_does_not_create_current_term(monkeypatch):
    _current_legislature()
    previous, _ = Legislature.objects.get_or_create(
        number=56,
        defaults={
            "start_date": timezone.localdate() - timedelta(days=1500),
            "end_date": timezone.localdate() - timedelta(days=500),
        },
    )
    term_person = Parliamentarian.objects.create(full_name="Pessoa do termo")
    source_person = Parliamentarian.objects.create(full_name="Pessoa da fonte")
    party = Party.objects.create(acronym="PT", name="PT")
    ParliamentarianTerm.objects.create(
        parliamentarian=term_person,
        legislature_number=previous,
        party=party,
        house="camara",
        role="Deputado",
        state="SP",
        external_id=778,
        start_date=previous.start_date,
        end_date=previous.end_date,
    )
    ParliamentarianProfileSource.objects.create(
        parliamentarian=source_person,
        source="camara",
        source_key="778",
        profile_values={},
    )
    camara = _BootstrapClient(
        [_camara_member(external_id=778, name="Nome qualquer")],
        {778: _camara_profile_named(778, "Nome qualquer")},
    )
    _prepare_task(monkeypatch, camara, _BootstrapClient([], {}))

    result = tasks.enrich_parliamentarian_profiles()

    assert result["terms"]["failed"] >= 1
    assert not ParliamentarianTerm.objects.filter(
        house="camara", external_id=778, legislature_number__number=57
    ).exists()
    assert Parliamentarian.objects.count() == 2


@pytest.mark.django_db
def test_existing_current_term_validates_conflicting_profile_source(monkeypatch):
    legislature = _current_legislature()
    term_person = Parliamentarian.objects.create(full_name="Pessoa atual")
    source_person = Parliamentarian.objects.create(full_name="Pessoa conflitante")
    old_party = Party.objects.create(acronym="OLD", name="OLD")
    term = ParliamentarianTerm.objects.create(
        parliamentarian=term_person,
        legislature_number=legislature,
        party=old_party,
        house="camara",
        role="Cargo antigo",
        state="RJ",
        external_id=779,
        start_date=legislature.start_date,
    )
    ParliamentarianProfileSource.objects.create(
        parliamentarian=source_person,
        source="camara",
        source_key="779",
        profile_values={},
    )
    camara = _BootstrapClient(
        [_camara_member(external_id=779, name="Pessoa atual", party="NEW", state="SP")],
        {779: _camara_profile_named(779, "Pessoa atual")},
    )
    _prepare_task(monkeypatch, camara, _BootstrapClient([], {}))

    result = tasks.enrich_parliamentarian_profiles()

    term.refresh_from_db()
    assert result["terms"]["failed"] >= 1
    assert term.party_id == old_party.pk
    assert term.role == "Cargo antigo"
    assert term.state == "RJ"
    assert term.end_date is None


@pytest.mark.django_db
def test_term_identity_across_any_legislature_precedes_names(monkeypatch):
    current = _current_legislature()
    previous, _ = Legislature.objects.get_or_create(
        number=56,
        defaults={"start_date": timezone.localdate() - timedelta(days=1500), "end_date": timezone.localdate() - timedelta(days=500)},
    )
    existing = Parliamentarian.objects.create(full_name="Pessoa com mandato anterior")
    party = Party.objects.create(acronym="PT", name="PT")
    ParliamentarianTerm.objects.create(
        parliamentarian=existing,
        legislature_number=previous,
        party=party,
        house="camara",
        role="Deputado",
        state="SP",
        external_id=1234,
        start_date=previous.start_date,
        end_date=previous.end_date,
    )
    camara = _BootstrapClient(
        [_camara_member(external_id=1234, name="Outro nome")],
        {1234: _camara_profile_named(1234, "Outro nome")},
    )
    _prepare_task(monkeypatch, camara, _BootstrapClient([], {}))

    tasks.enrich_parliamentarian_profiles()

    assert Parliamentarian.objects.count() == 1
    assert ParliamentarianTerm.objects.filter(
        parliamentarian=existing,
        legislature_number=current,
        external_id=1234,
    ).exists()


@pytest.mark.django_db
def test_matching_name_without_official_evidence_creates_new_person(monkeypatch):
    _current_legislature()
    existing = Parliamentarian.objects.create(full_name="Atila Lira")
    camara = _BootstrapClient(
        [_camara_member(external_id=74459, name="Atila Lira")],
        {74459: _camara_profile_named(74459, "Atila Lira")},
    )
    _prepare_task(monkeypatch, camara, _BootstrapClient([], {}))

    tasks.enrich_parliamentarian_profiles()

    assert Parliamentarian.objects.count() == 2
    assert not ParliamentarianTerm.objects.filter(parliamentarian=existing).exists()


@pytest.mark.django_db
def test_one_house_list_failure_does_not_block_other_house(monkeypatch):
    _current_legislature()
    camara = _BootstrapClient([], {}, failure=RuntimeError("camara list unavailable"))
    senado = _BootstrapClient([_senado_member()], {202: _senado_profile()})
    _prepare_task(monkeypatch, camara, senado)

    result = tasks.enrich_parliamentarian_profiles()

    assert result["processed"] == 1
    assert result["failed"] == 1
    assert result["terms"]["failed"] == 1
    assert result["failed"] == 1
    assert result["terms"]["senado"] == {
        "members": 1,
        "created": 1,
        "updated": 0,
        "failed": 0,
    }
    assert ParliamentarianTerm.objects.filter(house="senado").count() == 1


@pytest.mark.django_db
def test_empty_roster_never_closes_absent_terms(monkeypatch):
    legislature = _current_legislature()
    old = Parliamentarian.objects.create(full_name="Roster vazio")
    party = Party.objects.create(acronym="PT", name="PT")
    ParliamentarianTerm.objects.create(
        parliamentarian=old,
        legislature_number=legislature,
        party=party,
        house="camara",
        role="Deputado",
        state="SP",
        external_id=999,
        start_date=legislature.start_date,
    )
    _prepare_task(monkeypatch, _BootstrapClient([], {}), _BootstrapClient([], {}))

    result = tasks.enrich_parliamentarian_profiles()

    assert result["terms"]["camara"]["failed"] == 1
    assert ParliamentarianTerm.objects.get(external_id=999).end_date is None


@pytest.mark.django_db
def test_implausibly_small_roster_syncs_members_but_never_closes_absences(monkeypatch):
    legislature = _current_legislature()
    old = Parliamentarian.objects.create(full_name="Roster pequeno")
    party = Party.objects.create(acronym="PT", name="PT")
    ParliamentarianTerm.objects.create(
        parliamentarian=old,
        legislature_number=legislature,
        party=party,
        house="camara",
        role="Deputado",
        state="SP",
        external_id=999,
        start_date=legislature.start_date,
    )
    camara = _BootstrapClient([_camara_member()], {101: _camara_profile()})
    senado = _BootstrapClient([_senado_member()], {202: _senado_profile()})
    _prepare_task(monkeypatch, camara, senado, camara_minimum=2)

    result = tasks.enrich_parliamentarian_profiles()

    assert result["terms"]["camara"]["failed"] == 1
    assert ParliamentarianTerm.objects.filter(external_id=101).exists()
    assert ParliamentarianTerm.objects.get(external_id=999).end_date is None


@pytest.mark.django_db
def test_duplicate_roster_ids_block_absence_closure(monkeypatch):
    legislature = _current_legislature()
    old = Parliamentarian.objects.create(full_name="Roster duplicado")
    party = Party.objects.create(acronym="PT", name="PT")
    ParliamentarianTerm.objects.create(
        parliamentarian=old,
        legislature_number=legislature,
        party=party,
        house="camara",
        role="Deputado",
        state="SP",
        external_id=999,
        start_date=legislature.start_date,
    )
    camara = _BootstrapClient(
        [_camara_member(), _camara_member()], {101: _camara_profile()}
    )
    _prepare_task(monkeypatch, camara, _BootstrapClient([], {}))

    result = tasks.enrich_parliamentarian_profiles()

    assert result["terms"]["camara"]["failed"] == 1
    assert ParliamentarianTerm.objects.get(external_id=999).end_date is None


@pytest.mark.django_db
def test_wrong_payload_legislature_blocks_absence_closure(monkeypatch):
    legislature = _current_legislature()
    old = Parliamentarian.objects.create(full_name="Legislatura errada")
    party = Party.objects.create(acronym="PT", name="PT")
    ParliamentarianTerm.objects.create(
        parliamentarian=old,
        legislature_number=legislature,
        party=party,
        house="camara",
        role="Deputado",
        state="SP",
        external_id=999,
        start_date=legislature.start_date,
    )
    invalid = _camara_member()
    invalid["idLegislatura"] = 56
    _prepare_task(
        monkeypatch,
        _BootstrapClient([invalid], {101: _camara_profile()}),
        _BootstrapClient([], {}),
    )

    result = tasks.enrich_parliamentarian_profiles()

    assert result["terms"]["camara"]["failed"] == 1
    assert not ParliamentarianTerm.objects.filter(external_id=101).exists()
    assert ParliamentarianTerm.objects.get(external_id=999).end_date is None


def test_senate_live_payload_exposes_both_legislature_numbers():
    member = _senado_member()
    member["Mandato"].update(
        {
            "PrimeiraLegislaturaDoMandato": {"NumeroLegislatura": "56"},
            "SegundaLegislaturaDoMandato": {"NumeroLegislatura": "57"},
        }
    )

    assert tasks._payload_legislature_numbers(member, "senado") == {56, 57}


@pytest.mark.django_db
def test_successful_roster_closes_absent_active_terms(monkeypatch):
    today = timezone.localdate()
    legislature = _current_legislature()
    old = Parliamentarian.objects.create(full_name="Saiu da lista")
    party = Party.objects.create(acronym="PT", name="PT")
    ParliamentarianTerm.objects.create(
        parliamentarian=old,
        legislature_number=legislature,
        party=party,
        house="camara",
        role="Deputado",
        state="SP",
        external_id=999,
        start_date=legislature.start_date,
    )
    today_person = Parliamentarian.objects.create(full_name="Começa hoje")
    ParliamentarianTerm.objects.create(
        parliamentarian=today_person,
        legislature_number=legislature,
        party=party,
        house="camara",
        role="Deputado",
        state="SP",
        external_id=998,
        start_date=today,
    )
    camara = _BootstrapClient([_camara_member()], {101: _camara_profile()})
    _prepare_task(monkeypatch, camara, _BootstrapClient([], {}))

    tasks.enrich_parliamentarian_profiles()

    assert ParliamentarianTerm.objects.get(external_id=999).end_date == today - timedelta(days=1)
    assert ParliamentarianTerm.objects.get(external_id=998).end_date is None


@pytest.mark.django_db
def test_roster_failure_does_not_close_absent_terms(monkeypatch):
    legislature = _current_legislature()
    old = Parliamentarian.objects.create(full_name="Não fechar")
    party = Party.objects.create(acronym="PT", name="PT")
    ParliamentarianTerm.objects.create(
        parliamentarian=old,
        legislature_number=legislature,
        party=party,
        house="camara",
        role="Deputado",
        state="SP",
        external_id=999,
        start_date=legislature.start_date,
    )
    camara = _BootstrapClient([], {}, failure=RuntimeError("partial roster"))
    _prepare_task(monkeypatch, camara, _BootstrapClient([], {}))

    tasks.enrich_parliamentarian_profiles()

    assert ParliamentarianTerm.objects.get(external_id=999).end_date is None


@pytest.mark.django_db
def test_member_failure_does_not_close_absent_terms(monkeypatch):
    legislature = _current_legislature()
    old = Parliamentarian.objects.create(full_name="Não fechar")
    party = Party.objects.create(acronym="PT", name="PT")
    ParliamentarianTerm.objects.create(
        parliamentarian=old,
        legislature_number=legislature,
        party=party,
        house="camara",
        role="Deputado",
        state="SP",
        external_id=999,
        start_date=legislature.start_date,
    )
    invalid_member = {"id": "not-an-id", "nome": "Inválido"}
    camara = _BootstrapClient([invalid_member], {})
    _prepare_task(monkeypatch, camara, _BootstrapClient([], {}))

    tasks.enrich_parliamentarian_profiles()

    assert ParliamentarianTerm.objects.get(external_id=999).end_date is None


@pytest.mark.django_db
def test_roster_iteration_failure_does_not_close_absent_terms(monkeypatch):
    legislature = _current_legislature()
    old = Parliamentarian.objects.create(full_name="Não fechar")
    party = Party.objects.create(acronym="PT", name="PT")
    ParliamentarianTerm.objects.create(
        parliamentarian=old,
        legislature_number=legislature,
        party=party,
        house="camara",
        role="Deputado",
        state="SP",
        external_id=999,
        start_date=legislature.start_date,
    )

    class PartialRosterClient(_BootstrapClient):
        def list_current_members(self):
            yield _camara_member()
            raise RuntimeError("next page unavailable")

    camara = PartialRosterClient([_camara_member()], {101: _camara_profile()})
    _prepare_task(monkeypatch, camara, _BootstrapClient([], {}))

    tasks.enrich_parliamentarian_profiles()

    assert ParliamentarianTerm.objects.get(external_id=999).end_date is None


@pytest.mark.django_db
def test_existing_term_start_date_is_not_overwritten(monkeypatch):
    today = timezone.localdate()
    legislature = _current_legislature()
    existing = Parliamentarian.objects.create(full_name="Termo existente")
    party = Party.objects.create(acronym="PT", name="PT")
    term = ParliamentarianTerm.objects.create(
        parliamentarian=existing,
        legislature_number=legislature,
        party=party,
        house="camara",
        role="Deputado",
        state="SP",
        external_id=101,
        start_date=today - timedelta(days=10),
    )
    camara = _BootstrapClient([_camara_member()], {101: _camara_profile()})
    _prepare_task(monkeypatch, camara, _BootstrapClient([], {}))

    tasks.enrich_parliamentarian_profiles()

    term.refresh_from_db()
    assert term.start_date == today - timedelta(days=10)


@pytest.mark.django_db
def test_senate_substitute_uses_latest_active_exercise_start(monkeypatch):
    legislature = _current_legislature()
    first_exercise = timezone.localdate() - timedelta(days=60)
    latest_exercise = timezone.localdate() - timedelta(days=30)
    member = _senado_member(external_id="202", public_name="Suplente Atual")
    member["Mandato"] = {
        "DescricaoParticipacao": "Suplente",
        "Exercicios": {
            "Exercicio": [
                {"DataInicio": first_exercise.isoformat(), "DataFim": first_exercise.isoformat()},
                {"DataInicio": latest_exercise.isoformat()},
            ]
        },
    }
    senado = _BootstrapClient(
        [member], {202: _senado_profile(202, "Suplente Atual", "Suplente Atual")}
    )
    _prepare_task(monkeypatch, _BootstrapClient([], {}), senado)

    tasks.enrich_parliamentarian_profiles()

    term = ParliamentarianTerm.objects.get(house="senado", external_id=202)
    assert term.start_date == latest_exercise
    assert term.start_date >= legislature.start_date
    assert term.end_date is None


def test_senate_substitute_start_is_clamped_to_legislature():
    today = timezone.localdate()
    legislature_start = today - timedelta(days=100)
    mandate = {
        "DescricaoParticipacao": "1º Suplente",
        "Exercicios": {
            "Exercicio": {"DataInicio": (legislature_start - timedelta(days=500)).isoformat()}
        },
    }

    assert tasks._senado_substitute_start(
        mandate,
        today=today,
        fallback=legislature_start,
    ) == legislature_start


@pytest.mark.django_db
def test_party_aliases_and_case_are_canonicalized(monkeypatch):
    _current_legislature()
    existing_pcdb = Party.objects.create(acronym="PCdoB", name="PCdoB")
    existing_podemos = Party.objects.create(acronym="PODEMOS", name="Podemos")
    existing_mdb = Party.objects.create(acronym="mdb", name="MDB")
    members = [
        _camara_member(101, "Pessoa PCdoB", "PCDOB"),
        _camara_member(102, "Pessoa PODE", "PODE"),
        _camara_member(103, "Pessoa MDB", "MDB"),
    ]
    profiles = {external_id: _camara_profile(external_id) for external_id in (101, 102, 103)}
    camara = _BootstrapClient(members, profiles)
    _prepare_task(monkeypatch, camara, _BootstrapClient([], {}))

    tasks.enrich_parliamentarian_profiles()

    assert ParliamentarianTerm.objects.get(external_id=101).party_id == existing_pcdb.pk
    assert ParliamentarianTerm.objects.get(external_id=102).party_id == existing_podemos.pk
    assert ParliamentarianTerm.objects.get(external_id=103).party_id == existing_mdb.pk
    assert not Party.objects.filter(acronym="PODE").exists()
    assert not Party.objects.filter(acronym="PCDOB").exists()


@pytest.mark.django_db
def test_current_filter_excludes_missing_future_and_expired_terms():
    client = Client()
    today = timezone.localdate()
    legislature = _current_legislature()
    party = Party.objects.create(acronym="PT", name="PT")
    no_term = Parliamentarian.objects.create(full_name="Sem termo")
    future = Parliamentarian.objects.create(full_name="Futuro")
    expired = Parliamentarian.objects.create(full_name="Expirado")
    active = Parliamentarian.objects.create(full_name="Ativo")

    for parliamentarian, start, end, external_id in (
        (future, today + timedelta(days=1), None, 1),
        (expired, today - timedelta(days=10), today - timedelta(days=1), 2),
        (active, today - timedelta(days=10), today, 3),
    ):
        ParliamentarianTerm.objects.create(
            parliamentarian=parliamentarian,
            legislature_number=legislature,
            party=party,
            house="camara",
            role="Deputado",
            state="SP",
            external_id=external_id,
            start_date=start,
            end_date=end,
        )

    current = client.get("/api/v1/legislatures/parliamentarians?current=true")
    unfiltered = client.get("/api/v1/legislatures/parliamentarians?current=false")

    assert current.status_code == 200
    assert {item["full_name"] for item in current.json()["items"]} == {"Ativo"}
    assert {item["full_name"] for item in unfiltered.json()["items"]} == {
        no_term.full_name,
        future.full_name,
        expired.full_name,
        active.full_name,
    }


@pytest.mark.django_db
def test_current_filter_uses_one_term_for_all_predicates():
    client = Client()
    today = timezone.localdate()
    legislature = _current_legislature()
    expired_party = Party.objects.create(acronym="EXP", name="EXP")
    future_party = Party.objects.create(acronym="FUT", name="FUT")
    person = Parliamentarian.objects.create(full_name="Termos conflitantes")
    ParliamentarianTerm.objects.create(
        parliamentarian=person,
        legislature_number=legislature,
        party=expired_party,
        house="camara",
        role="Deputado",
        state="SP",
        external_id=700,
        start_date=today - timedelta(days=20),
        end_date=today - timedelta(days=1),
    )
    ParliamentarianTerm.objects.create(
        parliamentarian=person,
        legislature_number=legislature,
        party=future_party,
        house="senado",
        role="Senador",
        state="RJ",
        external_id=701,
        start_date=today + timedelta(days=1),
        end_date=None,
    )

    response = client.get(
        "/api/v1/legislatures/parliamentarians?current=true&house=camara"
    )

    assert response.status_code == 200
    assert response.json()["items"] == []
