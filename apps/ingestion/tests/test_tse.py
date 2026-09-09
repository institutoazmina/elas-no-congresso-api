import csv
import io
from types import SimpleNamespace
from zipfile import ZIP_DEFLATED, ZipFile

import httpx
import pytest

from apps.ingestion import tasks
from apps.ingestion.clients.tse import TSEArchiveLimitError, TSEClient
from apps.ingestion.tse import (
    TSECandidate,
    build_tse_index,
    match_tse_candidate,
    normalize_race_label,
    parse_tse_archive,
)
from apps.legislatures.services import profile_enrichment

ARCHIVE_URL = "https://cdn.tse.test/consulta_cand_2022.zip"
CSV_FIELDS = [
    "SQ_CANDIDATO",
    "NM_CANDIDATO",
    "NM_URNA_CANDIDATO",
    "SG_UF",
    "DS_CARGO",
    "SG_PARTIDO",
    "DS_COR_RACA",
    "ANO_ELEICAO",
    "NR_CPF_CANDIDATO",
]


def _archive(rows, *, malformed_member=None):
    csv_buffer = io.StringIO(newline="")
    writer = csv.DictWriter(csv_buffer, fieldnames=CSV_FIELDS, delimiter=";")
    writer.writeheader()
    writer.writerows(rows)
    output = io.BytesIO()
    with ZipFile(output, "w", ZIP_DEFLATED) as archive:
        archive.writestr("consulta_cand_2022_BRASIL.csv", csv_buffer.getvalue().encode("latin-1"))
        if malformed_member is not None:
            archive.writestr("ignored.csv", malformed_member)
    return output.getvalue()


def _row(
    *,
    sq="9001",
    name="JOSE DA SILVA",
    uf="SP",
    office="DEPUTADO FEDERAL",
    party="PT",
    race="PARDA",
):
    return {
        "SQ_CANDIDATO": sq,
        "NM_CANDIDATO": name,
        "NM_URNA_CANDIDATO": "ZE SILVA",
        "SG_UF": uf,
        "DS_CARGO": office,
        "SG_PARTIDO": party,
        "DS_COR_RACA": race,
        "ANO_ELEICAO": "2022",
        "NR_CPF_CANDIDATO": "must-not-be-read",
    }


def test_parser_retains_only_matching_and_provenance_fields_from_latin1_csv():
    candidates = parse_tse_archive(
        _archive([_row(name="JOÃO D'ÁVILA", race="INDÍGENA")]),
        default_election_year=2022,
        archive_url=ARCHIVE_URL,
    )

    assert candidates == [
        TSECandidate(
            sq_candidato="9001",
            full_name="JOÃO D'ÁVILA",
            ballot_name="ZE SILVA",
            state="SP",
            office="DEPUTADO FEDERAL",
            party="PT",
            raw_race="INDÍGENA",
            election_year=2022,
            archive_url=ARCHIVE_URL,
        )
    ]
    assert "cpf" not in vars(candidates[0])
    assert candidates[0].archive_url == ARCHIVE_URL


def test_parser_skips_malformed_rows_and_members_without_failing_archive():
    rows = [_row(), {**_row(sq=""), "NM_CANDIDATO": "Sem chave"}]
    candidates = parse_tse_archive(_archive(rows, malformed_member=b"\xff\xfe\x00"))

    assert [candidate.sq_candidato for candidate in candidates] == ["9001"]


def test_parser_rejects_uncompressed_size_limit():
    with pytest.raises(TSEArchiveLimitError):
        parse_tse_archive(_archive([_row()]), max_uncompressed_bytes=1)


def test_tse_client_streams_archive_with_injected_httpx_transport_and_size_limit():
    archive = _archive([_row()])
    requests = []

    def handler(request):
        requests.append(request.url)
        return httpx.Response(200, content=archive)

    http_client = httpx.Client(transport=httpx.MockTransport(handler))
    client = TSEClient(
        client=http_client,
        archive_url=ARCHIVE_URL,
        max_download_bytes=len(archive) + 1,
    )

    assert client.download_archive() == archive
    assert requests == [httpx.URL(ARCHIVE_URL)]


def test_tse_client_rejects_advertised_oversized_response():
    def handler(_request):
        return httpx.Response(200, content=b"small", headers={"content-length": "100"})

    client = TSEClient(
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        archive_url=ARCHIVE_URL,
        max_download_bytes=3,
    )

    with pytest.raises(TSEArchiveLimitError):
        client.download_archive()


def _term(*, house="camara", state="SP", name="José da Silva", party="PT", external_id=101):
    return SimpleNamespace(
        house=house,
        state=state,
        external_id=external_id,
        parliamentarian=SimpleNamespace(full_name=name),
        party=SimpleNamespace(acronym=party),
    )


def test_matcher_requires_exact_house_office_uf_and_name_and_can_use_unique_party_tiebreaker():
    index = build_tse_index(
        [
            TSECandidate("1", "JOSE DA SILVA", "ZE", "SP", "DEPUTADO FEDERAL", "MDB", "PRETA", 2022),
            TSECandidate("2", "JOSE DA SILVA", "ZE", "SP", "DEPUTADO FEDERAL", "PT", "PARDA", 2022),
            TSECandidate("3", "JOSE DA SILVA", "ZE", "RJ", "SENADOR", "PT", "PARDA", 2022),
        ]
    )

    result = match_tse_candidate(index, _term())
    assert result.status == "matched"
    assert result.candidate is not None
    assert result.candidate.sq_candidato == "2"

    assert match_tse_candidate(index, _term(party="PSOL")).status == "ambiguous"
    assert match_tse_candidate(index, _term(state="RJ")).status == "unresolved"
    assert match_tse_candidate(index, _term(house="senado", state="SP")).status == "unresolved"


def test_matcher_limits_camara_to_2022_and_senado_to_2018_or_2022():
    index = build_tse_index(
        [
            TSECandidate("2018", "JOSE DA SILVA", "ZE", "SP", "DEPUTADO FEDERAL", "PT", "PRETA", 2018),
            TSECandidate("2022", "JOSE DA SILVA", "ZE", "SP", "DEPUTADO FEDERAL", "PT", "PARDA", 2022),
            TSECandidate("sen-2018", "JOSE DA SILVA", "ZE", "SP", "SENADOR", "PT", "PRETA", 2018),
            TSECandidate("sen-2022", "JOSE DA SILVA", "ZE", "SP", "SENADOR", "PT", "PARDA", 2022),
        ]
    )

    camara = match_tse_candidate(index, _term())
    assert camara.status == "matched"
    assert camara.candidate is not None
    assert camara.candidate.sq_candidato == "2022"
    assert match_tse_candidate(index, _term(house="senado")).status == "ambiguous"


def test_senado_party_can_leave_one_candidate_across_years_without_guessing():
    index = build_tse_index(
        [
            TSECandidate("2018", "JOSE DA SILVA", "ZE", "SP", "SENADOR", "PT", "PRETA", 2018),
            TSECandidate("2022", "JOSE DA SILVA", "ZE", "SP", "SENADOR", "MDB", "PARDA", 2022),
        ]
    )

    result = match_tse_candidate(index, _term(house="senado", party="PT"))
    assert result.status == "matched"
    assert result.candidate is not None
    assert result.candidate.sq_candidato == "2018"


def test_senado_same_year_party_tiebreaker_is_allowed():
    index = build_tse_index(
        [
            TSECandidate("2018-pt", "JOSE DA SILVA", "ZE", "SP", "SENADOR", "PT", "PRETA", 2018),
            TSECandidate("2018-mdb", "JOSE DA SILVA", "ZE", "SP", "SENADOR", "MDB", "PARDA", 2018),
        ]
    )

    result = match_tse_candidate(index, _term(house="senado", party="PT"))
    assert result.status == "matched"
    assert result.candidate is not None
    assert result.candidate.sq_candidato == "2018-pt"


@pytest.mark.parametrize("source", ["tse", "legacy"])
def test_non_official_profile_sources_are_not_activity_gated(monkeypatch, source):
    profile = SimpleNamespace(
        source=source,
        profile_values={"race": "parda"},
        last_seen_at=1,
        pk=1,
    )
    monkeypatch.setattr(profile_enrichment, "_official_is_active_or_recent", lambda *args: False)

    assert profile_enrichment._resolved_values([profile], house="senado") == {"race": "parda"}


def test_tse_source_precedes_legacy_even_when_legacy_is_newer():
    tse_profile = SimpleNamespace(
        source="tse",
        profile_values={"race": "parda"},
        last_seen_at=1,
        pk=1,
    )
    legacy_profile = SimpleNamespace(
        source="legacy",
        profile_values={"race": "branca"},
        last_seen_at=2,
        pk=2,
    )

    assert profile_enrichment._resolved_values(
        [legacy_profile, tse_profile], house="senado"
    ) == {"race": "parda"}


def test_archive_loader_combines_years_and_keeps_partial_failures(monkeypatch):
    urls = {
        2018: "https://cdn.tse.test/consulta_cand_2018.zip",
        2022: "https://cdn.tse.test/consulta_cand_2022.zip",
    }
    requests = []

    class _ArchiveClient:
        def __init__(self, *, archive_url):
            self.archive_url = archive_url

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def download_archive(self):
            requests.append(self.archive_url)
            if self.archive_url == urls[2018]:
                raise RuntimeError("2018 unavailable")
            return _archive([_row(name="JOSE DA SILVA")])

    monkeypatch.setattr(tasks.settings, "TSE_CANDIDATES_ARCHIVE_URLS", urls)
    monkeypatch.setattr(tasks, "TSEClient", _ArchiveClient)

    index, failed_archives = tasks._load_tse_index()

    assert requests == [urls[2018], urls[2022]]
    assert failed_archives == 1
    candidates = next(iter(index.values()))
    assert candidates[0].election_year == 2022
    assert candidates[0].archive_url == urls[2022]


def test_race_labels_are_normalized_to_stable_portuguese_values():
    assert normalize_race_label("BRANCA") == "branca"
    assert normalize_race_label("INDÍGENA") == "indígena"
    assert normalize_race_label("NÃO INFORMADO") == "não informado"
    assert normalize_race_label("valor desconhecido") is None
