from datetime import date, timedelta
from types import SimpleNamespace

import pytest
from django.utils import timezone

from apps.committees.models import (
    Caucus,
    CaucusMembership,
    Committee,
    CommitteeMembership,
    CommitteePresidency,
)
from apps.ingestion import tasks
from apps.ingestion.institutional_relationships import (
    parse_provider_date,
    persist_official_relationships,
    persist_senado_fronts,
)
from apps.ingestion.senado_fronts import SenadoFrontSnapshot, SenateFrontMember
from apps.legislatures.models import (
    Legislature,
    Parliamentarian,
    ParliamentarianPost,
    ParliamentarianTerm,
    Party,
)

CAMARA_BASE_URL = "https://dadosabertos.camara.leg.br/api/v2"
SENADO_BASE_URL = "https://legis.senado.leg.br/dadosabertos"


def _make_term(*, external_id, house, name=None):
    today = timezone.localdate()
    legislature, _ = Legislature.objects.get_or_create(
        number=57,
        defaults={"start_date": date(2023, 2, 1), "end_date": date(2027, 1, 31)},
    )
    parliamentarian = Parliamentarian.objects.create(
        full_name=name or f"Parlamentar {house} {external_id}"
    )
    party = Party.objects.create(acronym=f"P{house}{external_id}", name="Partido")
    return ParliamentarianTerm.objects.create(
        parliamentarian=parliamentarian,
        legislature_number=legislature,
        party=party,
        house=house,
        role="Parlamentar",
        state="SP",
        external_id=external_id,
        start_date=today - timedelta(days=10),
        end_date=today + timedelta(days=10),
    )


class _CamaraInstitutionalClient:
    base_url = CAMARA_BASE_URL

    def __init__(self, profile, fronts, organs):
        self.profile = profile
        self.fronts = fronts
        self.organs = organs

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def fetch_profile(self, external_id):
        assert self.profile["id"] == external_id
        return self.profile

    def fetch_deputy_fronts(self, external_id):
        assert self.profile["id"] == external_id
        return self.fronts

    def fetch_deputy_organs(self, external_id):
        assert self.profile["id"] == external_id
        return self.organs


class _SenadoInstitutionalClient:
    base_url = SENADO_BASE_URL

    def __init__(self, profile, committees, affiliations, leaderships, posts):
        self.profile = profile
        self.committees = committees
        self.affiliations = affiliations
        self.leaderships = leaderships
        self.posts = posts

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def fetch_profile(self, external_id):
        assert self.profile["IdentificacaoParlamentar"]["CodigoParlamentar"] == str(external_id)
        return self.profile

    def fetch_senator_committees(self, external_id):
        return self.committees

    def fetch_senator_party_affiliations(self, external_id):
        return self.affiliations

    def fetch_senator_leaderships(self, external_id):
        return self.leaderships

    def fetch_senator_posts(self, external_id):
        return self.posts


def _camara_client(external_id=101, *, sparse=False):
    return _CamaraInstitutionalClient(
        profile={
            "id": external_id,
            "uri": f"{CAMARA_BASE_URL}/deputados/{external_id}",
            "nomeCivil": "Deputada Oficial",
            "sexo": "F",
            "ultimoStatus": {"nome": "Deputada Pública"},
        },
        fronts=(
            [
                {
                    "id": 700,
                    "uri": f"{CAMARA_BASE_URL}/frentes/700",
                    "titulo": None if sparse else "Frente pela Igualdade",
                    "dataInicio": None if sparse else "2024-01-01",
                    "dataFim": None if sparse else "2024-01-01",
                    "idLegislatura": 57,
                }
            ]
        ),
        organs=[
            {
                "idOrgao": 88,
                "uriOrgao": f"{CAMARA_BASE_URL}/orgaos/88",
                "siglaOrgao": None if sparse else "CCJC",
                "nomeOrgao": None if sparse else "Comissão de Constituição",
                "tipoOrgao": "Comissão Permanente",
                "titulo": None if sparse else "Titular",
                "cargo": None if sparse else "Presidente",
                "dataInicio": None if sparse else "2024-01-01",
                "dataFim": None if sparse else "2024-01-01",
            }
        ],
    )


def _senado_client(external_id=202):
    return _SenadoInstitutionalClient(
        profile={
            "IdentificacaoParlamentar": {
                "CodigoParlamentar": str(external_id),
                "NomeCompletoParlamentar": "Senador Oficial",
                "NomeParlamentar": "Senador Público",
                "SexoParlamentar": "Masculino",
                "UrlPaginaParlamentar": f"{SENADO_BASE_URL}/senador/{external_id}",
            }
        },
        committees=[
            {
                "CodigoComissao": "40",
                "SiglaComissao": "CAS",
                "NomeComissao": "Comissão de Assuntos Sociais",
                "DataInicio": "2024-01-01",
                "DataFim": "2024-01-01",
                "CargoComissao": "Presidente",
            }
        ],
        affiliations=[
            {
                "CodigoPartido": "MDB",
                "NomePartido": "Movimento Democrático Brasileiro",
                "DataFiliacao": "2023-02-01",
            },
            {
                "CodigoBancada": "B-1",
                "NomeBancada": "Bancada Oficial do Senado",
                "DataInicio": "2024-01-01",
                "DataFim": "2024-01-01",
            },
        ],
        leaderships=[
            {
                "CodigoLideranca": "L-9",
                "DescricaoTipoLideranca": "Líder da bancada",
                "CodigoBancada": "B-1",
                "NomeBancada": "Bancada Oficial do Senado",
                "DataInicio": "2024-01-01",
                "DataFim": "2024-01-01",
            }
        ],
        posts=[
            {
                "CodigoCargo": "C-3",
                "DescricaoCargo": "Presidente da Comissão",
                "NomeOrgao": "Mesa do Senado",
                "DataInicio": "2024-01-01",
                "DataFim": "2024-01-01",
            }
        ],
    )


def test_provider_date_is_explicit_and_accepts_same_day():
    parsed = parse_provider_date("2024-01-01")
    assert parsed == date(2024, 1, 1)
    assert parsed == parse_provider_date("2024-01-01")
    assert parse_provider_date(None) is None
    assert parse_provider_date("not-a-date") is None


def test_only_an_explicit_committee_president_role_is_classified_as_presidency():
    from apps.ingestion.institutional_relationships import is_committee_president

    assert is_committee_president({"cargo": "Presidente"}) is True
    assert is_committee_president({"CargoComissao": "Presidente da Comissão"}) is True
    assert is_committee_president({"cargo": "Vice-Presidente"}) is False
    assert is_committee_president({"cargo": "Vice-Presidente", "titulo": "Presidente"}) is False
    assert is_committee_president({"CargoComissao": "Titular"}) is False
    assert is_committee_president({"DescricaoTipoLideranca": "Líder de bancada"}) is False


@pytest.mark.django_db
def test_camara_relationship_service_is_idempotent_and_preserves_known_values():
    term = _make_term(external_id=101, house="camara")
    first_client = _camara_client()
    persist_official_relationships(term=term, client=first_client)

    sparse_client = _camara_client(sparse=True)
    persist_official_relationships(term=term, client=sparse_client)

    assert Caucus.objects.count() == 1
    assert CaucusMembership.objects.count() == 1
    assert Committee.objects.count() == 1
    assert CommitteeMembership.objects.count() == 1
    assert CommitteePresidency.objects.count() == 1
    caucus = Caucus.objects.get()
    committee = Committee.objects.get()
    assert caucus.name == "Frente pela Igualdade"
    assert caucus.start_date == date(2024, 1, 1)
    assert CaucusMembership.objects.get().role is None
    assert committee.name == "Comissão de Constituição"
    assert committee.acronym == "CCJC"
    assert CommitteeMembership.objects.get().role == "Titular"
    assert CommitteeMembership.objects.get().start_date == date(2024, 1, 1)
    presidency = CommitteePresidency.objects.get()
    assert presidency.source_key == "orgao:88:member:101:presidency"
    assert presidency.legislature == term.legislature_number
    assert presidency.start_date == date(2024, 1, 1)
    assert presidency.end_date == date(2024, 1, 1)


@pytest.mark.django_db
def test_camara_relationship_service_reuses_same_front_with_different_provider_ids():
    term = _make_term(external_id=101, house="camara")
    client = _camara_client()
    client.fronts.append(
        {
            **client.fronts[0],
            "id": 701,
            "uri": f"{CAMARA_BASE_URL}/frentes/701",
        }
    )

    persist_official_relationships(term=term, client=client)

    assert Caucus.objects.count() == 1
    assert Caucus.objects.get().source_key == "front:700"
    assert CaucusMembership.objects.count() == 2


@pytest.mark.django_db
def test_enrichment_task_persists_camara_and_senado_institutional_relationships(monkeypatch):
    camara_term = _make_term(external_id=101, house="camara")
    senado_term = _make_term(external_id=202, house="senado")
    monkeypatch.setattr(tasks, "CamaraClient", lambda: _camara_client())
    monkeypatch.setattr(tasks, "SenadoClient", lambda: _senado_client())
    monkeypatch.setattr(tasks, "_load_tse_index", lambda: ({}, 0))
    monkeypatch.setattr(
        tasks,
        "_load_senado_front_snapshot",
        lambda: SimpleNamespace(fronts=(), failed_fronts=0),
    )

    result = tasks.enrich_parliamentarian_profiles()

    assert result["processed"] == 2
    assert result["failed"] == 0
    assert result["camara"] == {"processed": 1, "failed": 0}
    assert result["senado"] == {"processed": 1, "failed": 0}
    assert Caucus.objects.filter(kind="frente", house="camara").count() == 1
    assert Caucus.objects.filter(kind="bancada", house="senado").count() == 1
    assert Caucus.objects.filter(kind="bancada", name__icontains="Movimento").count() == 0
    assert Committee.objects.filter(house="camara", source_key="orgao:88").exists()
    assert Committee.objects.filter(house="senado", source_key="comissao:40").exists()
    assert CommitteePresidency.objects.filter(
        committee__source_key="orgao:88",
        parliamentarian=camara_term.parliamentarian,
        source_key="orgao:88:member:101:presidency",
        legislature=camara_term.legislature_number,
        start_date=date(2024, 1, 1),
        end_date=date(2024, 1, 1),
    ).exists()
    assert CommitteePresidency.objects.filter(
        committee__source_key="comissao:40",
        parliamentarian=senado_term.parliamentarian,
        source_key="comissao:40:member:202:presidency",
    ).exists()
    assert CommitteeMembership.objects.filter(
        parliamentarian=camara_term.parliamentarian,
        legislature=camara_term.legislature_number,
        source_key="orgao:88:member:101",
    ).exists()
    assert CommitteeMembership.objects.filter(
        parliamentarian=senado_term.parliamentarian,
        legislature=senado_term.legislature_number,
        source_key="comissao:40:member:202",
    ).exists()
    assert ParliamentarianPost.objects.filter(
        parliamentarian=senado_term.parliamentarian,
        source_key="lideranca:L-9:member:202",
    ).exists()
    assert ParliamentarianPost.objects.filter(
        parliamentarian=senado_term.parliamentarian,
        source_key="cargo:C-3:member:202",
    ).exists()


@pytest.mark.django_db
def test_senado_front_snapshot_persists_current_senators_by_official_id_and_is_idempotent():
    term = _make_term(external_id=202, house="senado")
    front = SenadoFrontSnapshot(
        name="Frente Parlamentar de Cuidado",
        acronym="FPC",
        status="Ativa",
        council_url="https://www25.senado.leg.br/web/atividade/conselhos/-/conselho/fpc",
        composition_url="https://legis.senado.leg.br/comissoes/composicao_comissao?codcol=2696",
        codcol="2696",
        members=(
            SenateFrontMember(
                house="senado",
                external_id=202,
                profile_url="https://www25.senado.leg.br/web/senadores/senador/-/perfil/202",
                role="Presidente",
            ),
            SenateFrontMember(
                house="camara",
                external_id=101,
                profile_url="https://www.camara.leg.br/deputados/101",
                role="Membro",
            ),
        ),
    )

    first = persist_senado_fronts(fronts=[front], terms=[term])
    second = persist_senado_fronts(fronts=[front], terms=[term])

    assert first == {"processed": 1, "failed": 0, "memberships": 1}
    assert second == first
    assert Caucus.objects.filter(
        source="senado", source_key="2696", house="senado", kind="frente"
    ).count() == 1
    assert Caucus.objects.get(source="senado", source_key="2696").description == "Ativa"
    assert CaucusMembership.objects.filter(
        source="senado", source_key="2696:member:senado:202", parliamentarian=term.parliamentarian
    ).count() == 1
    assert CaucusMembership.objects.filter(source_key__contains=":camara:").count() == 0


@pytest.mark.django_db
def test_relationship_failure_marks_that_parliamentarian_failed(monkeypatch):
    _make_term(external_id=301, house="camara")
    _make_term(external_id=302, house="camara")

    class _Client:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def fetch_profile(self, external_id):
            return {"id": external_id, "nomeCivil": f"Pessoa {external_id}"}

    def persist(*, term, client):
        if term.external_id == 301:
            raise RuntimeError("institutional endpoint unavailable")

    monkeypatch.setattr(tasks, "CamaraClient", _Client)
    monkeypatch.setattr(tasks, "SenadoClient", _Client)
    monkeypatch.setattr(tasks, "_load_tse_index", lambda: ({}, 0))
    monkeypatch.setattr(
        tasks,
        "_load_senado_front_snapshot",
        lambda: SimpleNamespace(fronts=(), failed_fronts=0),
    )
    monkeypatch.setattr(tasks, "persist_official_relationships", persist)

    result = tasks.enrich_parliamentarian_profiles()

    assert result["camara"] == {"processed": 1, "failed": 1}
    assert result["processed"] == 1
    assert result["failed"] == 1


@pytest.mark.django_db
def test_negative_committee_roles_do_not_create_presidencies():
    term = _make_term(external_id=303, house="camara")
    client = _camara_client(external_id=303)
    client.organs = [
        {
            "idOrgao": 89,
            "siglaOrgao": "CPI",
            "nomeOrgao": "Comissão Parlamentar de Inquérito",
            "tipoOrgao": "Comissão Temporária",
            "cargo": "Vice-Presidente",
            "dataInicio": "2024-01-01",
            "dataFim": "2024-01-01",
        },
        {
            "idOrgao": 90,
            "siglaOrgao": "CCJ",
            "nomeOrgao": "Comissão de Justiça",
            "tipoOrgao": "Comissão Permanente",
            "cargo": "Titular",
            "dataInicio": "2024-01-01",
            "dataFim": "2024-01-01",
        },
    ]

    persist_official_relationships(term=term, client=client)

    assert CommitteePresidency.objects.count() == 0
