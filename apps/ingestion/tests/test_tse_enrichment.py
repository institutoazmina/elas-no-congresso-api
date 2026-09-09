import csv
import io
from datetime import date, timedelta
from types import SimpleNamespace
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from django.utils import timezone

from apps.ingestion import tasks
from apps.legislatures.models import (
    Legislature,
    Parliamentarian,
    ParliamentarianProfileSource,
    ParliamentarianTerm,
    Party,
)
from apps.legislatures.services.profile_enrichment import upsert_source_profile


def _archive(rows):
    fields = [
        "SQ_CANDIDATO",
        "NM_CANDIDATO",
        "NM_URNA_CANDIDATO",
        "SG_UF",
        "DS_CARGO",
        "SG_PARTIDO",
        "DS_COR_RACA",
        "ANO_ELEICAO",
    ]
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=fields, delimiter=";")
    writer.writeheader()
    writer.writerows(rows)
    output = io.BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("consulta_cand_2022_BRASIL.csv", buffer.getvalue().encode("latin-1"))
    return output.getvalue()


def _candidate(sq, name, uf, office, party, race, year=2022):
    return {
        "SQ_CANDIDATO": str(sq),
        "NM_CANDIDATO": name,
        "NM_URNA_CANDIDATO": name,
        "SG_UF": uf,
        "DS_CARGO": office,
        "SG_PARTIDO": party,
        "DS_COR_RACA": race,
        "ANO_ELEICAO": str(year),
    }


def _term(*, external_id, house, name, state, party):
    today = timezone.localdate()
    legislature, _ = Legislature.objects.get_or_create(
        number=57,
        defaults={"start_date": date(2023, 2, 1), "end_date": date(2027, 1, 31)},
    )
    parliamentarian = Parliamentarian.objects.create(full_name=name)
    party_obj = Party.objects.create(acronym=party, name=party)
    return ParliamentarianTerm.objects.create(
        parliamentarian=parliamentarian,
        legislature_number=legislature,
        party=party_obj,
        house=house,
        role="Parlamentar",
        state=state,
        external_id=external_id,
        start_date=today - timedelta(days=10),
        end_date=today + timedelta(days=10),
    )


class _ProfileClient:
    def __init__(self, house, profiles):
        self.house = house
        self.profiles = profiles

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def fetch_profile(self, external_id):
        return self.profiles[external_id]

    def fetch_deputy_fronts(self, _external_id):
        return []

    def fetch_deputy_organs(self, _external_id):
        return []

    def fetch_senator_committees(self, _external_id):
        return []

    def fetch_senator_party_affiliations(self, _external_id):
        return []

    def fetch_senator_leaderships(self, _external_id):
        return []

    def fetch_senator_posts(self, _external_id):
        return []


class _TSEClient:
    def __init__(self, archives, *, archive_url, **_kwargs):
        self.archives = archives
        self.archive_url = archive_url
        self.downloads = 0
        self.requested_urls = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def download_archive(self):
        self.downloads += 1
        self.requested_urls.append(self.archive_url)
        return self.archives[self.archive_url]


@pytest.mark.django_db
def test_task_projects_one_archive_match_per_current_term_and_is_idempotent(monkeypatch):
    camara_term = _term(
        external_id=101,
        house="camara",
        name="Maria José da Silva",
        state="SP",
        party="PT",
    )
    senado_term = _term(
        external_id=202,
        house="senado",
        name="Ana Maria Souza",
        state="RJ",
        party="MDB",
    )
    archive_2022 = _archive(
        [
            _candidate("9001", "MARIA JOSE DA SILVA", "SP", "DEPUTADO FEDERAL", "PT", "PRETA"),
        ]
    )
    archive_2018 = _archive(
        [
            _candidate(
                "9002",
                "ANA MARIA SOUZA",
                "RJ",
                "SENADOR",
                "MDB",
                "PARDA",
                year=2018,
            ),
        ]
    )
    archive_urls = {
        2018: "https://cdn.tse.test/consulta_cand_2018.zip",
        2022: "https://cdn.tse.test/consulta_cand_2022.zip",
    }
    archives = {
        archive_urls[2018]: archive_2018,
        archive_urls[2022]: archive_2022,
    }
    tse_clients = []

    def make_tse_client(**kwargs):
        client = _TSEClient(archives, **kwargs)
        tse_clients.append(client)
        return client

    monkeypatch.setattr(tasks, "TSEClient", make_tse_client)
    monkeypatch.setattr(
        tasks,
        "_load_senado_front_snapshot",
        lambda: SimpleNamespace(fronts=(), failed_fronts=0),
    )
    monkeypatch.setattr(
        tasks,
        "CamaraClient",
        lambda: _ProfileClient("camara", {101: {"id": 101, "nomeCivil": camara_term.parliamentarian.full_name}}),
    )
    monkeypatch.setattr(
        tasks,
        "SenadoClient",
        lambda: _ProfileClient(
            "senado",
            {
                202: {
                    "IdentificacaoParlamentar": {
                        "CodigoParlamentar": "202",
                        "NomeCompletoParlamentar": senado_term.parliamentarian.full_name,
                    }
                }
            },
        ),
    )
    monkeypatch.setattr(tasks, "persist_official_relationships", lambda **kwargs: {})

    first = tasks.enrich_parliamentarian_profiles()
    second = tasks.enrich_parliamentarian_profiles()

    assert first["tse"] == {"processed": 2, "unresolved": 0, "ambiguous": 0, "failed": 0}
    assert second["tse"] == first["tse"]
    assert first["processed"] == second["processed"] == 2
    assert sum(client.downloads for client in tse_clients) == 4
    assert [
        url
        for client in tse_clients
        for url in client.requested_urls
    ] == [
        archive_urls[2018],
        archive_urls[2022],
        archive_urls[2018],
        archive_urls[2022],
    ]
    camara_term.parliamentarian.refresh_from_db()
    senado_term.parliamentarian.refresh_from_db()
    assert camara_term.parliamentarian.race == "preta"
    assert senado_term.parliamentarian.race == "parda"
    assert ParliamentarianProfileSource.objects.filter(source="tse").count() == 2
    assert ParliamentarianProfileSource.objects.filter(source="tse", source_key="9001").count() == 1
    snapshot = ParliamentarianProfileSource.objects.get(source="tse", source_key="9001")
    assert snapshot.profile_values == {"race": "preta"}
    assert snapshot.source_url == archive_urls[2022]
    assert snapshot.metadata["sq_candidato"] == "9001"
    assert snapshot.metadata["raw_race"] == "PRETA"
    assert snapshot.metadata["term_external_id"] == 101
    assert "cpf" not in snapshot.metadata
    senator_snapshot = ParliamentarianProfileSource.objects.get(source="tse", source_key="9002")
    assert senator_snapshot.source_url == archive_urls[2018]
    assert senator_snapshot.metadata["election_year"] == 2018


@pytest.mark.django_db
def test_tse_ambiguity_and_unresolved_are_counted_without_blocking_official_profile(monkeypatch):
    ambiguous_term = _term(
        external_id=301,
        house="camara",
        name="Nome Ambíguo",
        state="SP",
        party="PT",
    )
    unresolved_term = _term(
        external_id=302,
        house="camara",
        name="Nome Ausente",
        state="RJ",
        party="MDB",
    )
    archive = _archive(
        [
            _candidate("9101", "NOME AMBIGUO", "SP", "DEPUTADO FEDERAL", "PT", "PRETA"),
            _candidate("9102", "NOME AMBIGUO", "SP", "DEPUTADO FEDERAL", "PT", "PARDA"),
        ]
    )
    archive_urls = {
        "https://cdn.tse.test/consulta_cand_2018.zip": archive,
        "https://cdn.tse.test/consulta_cand_2022.zip": archive,
    }
    monkeypatch.setattr(tasks, "TSEClient", lambda **kwargs: _TSEClient(archive_urls, **kwargs))
    monkeypatch.setattr(
        tasks,
        "_load_senado_front_snapshot",
        lambda: SimpleNamespace(fronts=(), failed_fronts=0),
    )
    monkeypatch.setattr(
        tasks,
        "CamaraClient",
        lambda: _ProfileClient(
            "camara",
            {
                301: {"id": 301, "nomeCivil": ambiguous_term.parliamentarian.full_name},
                302: {"id": 302, "nomeCivil": unresolved_term.parliamentarian.full_name},
            },
        ),
    )
    monkeypatch.setattr(tasks, "SenadoClient", lambda: _ProfileClient("senado", {}))
    monkeypatch.setattr(tasks, "persist_official_relationships", lambda **kwargs: {})

    result = tasks.enrich_parliamentarian_profiles()

    assert result["camara"] == {"processed": 2, "failed": 0}
    assert result["tse"] == {"processed": 0, "unresolved": 1, "ambiguous": 1, "failed": 0}


@pytest.mark.django_db
def test_manual_race_has_priority_over_tse_race():
    term = _term(
        external_id=401,
        house="camara",
        name="Pessoa Manual",
        state="SP",
        party="PT",
    )
    upsert_source_profile(
        source="manual",
        source_key="manual-401",
        external_id=401,
        house="camara",
        profile_values={"race": "indígena"},
    )
    upsert_source_profile(
        source="tse",
        source_key="9201",
        external_id=401,
        house="camara",
        profile_values={"race": "parda"},
        metadata={"sq_candidato": "9201", "raw_race": "PARDA", "term_external_id": 401},
    )

    term.parliamentarian.refresh_from_db()
    assert term.parliamentarian.race == "indígena"
