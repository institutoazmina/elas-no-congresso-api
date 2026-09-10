"""Parser and conservative matcher for the TSE self-declared race archive."""

import csv
import io
import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from zipfile import BadZipFile, ZipFile

TSE_MAX_MEMBERS = 1_000
TSE_MAX_UNCOMPRESSED_BYTES = 512 * 1024 * 1024
TSE_MAX_MEMBER_BYTES = 128 * 1024 * 1024
TSE_MAX_COMPRESSION_RATIO = 1_000
_TSE_FIELDS = {
    "SQ_CANDIDATO",
    "NM_CANDIDATO",
    "NM_URNA_CANDIDATO",
    "SG_UF",
    "DS_CARGO",
    "SG_PARTIDO",
    "DS_COR_RACA",
    "DT_NASCIMENTO",
    "DS_GRAU_INSTRUCAO",
    "DS_OCUPACAO",
    "ANO_ELEICAO",
}


class TSEArchiveLimitError(ValueError):
    """The archive exceeds a safe structural or uncompressed-size bound."""


@dataclass(frozen=True)
class TSECandidate:
    sq_candidato: str
    full_name: str
    ballot_name: str | None
    state: str
    office: str
    party: str | None
    raw_race: str | None
    election_year: int
    birth_date: date | None = None
    education: str | None = None
    occupation: str | None = None
    archive_url: str | None = None


@dataclass(frozen=True)
class TSEMatch:
    status: str
    candidate: TSECandidate | None = None


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _header_map(row: Mapping) -> dict[str, object]:
    return {
        str(key).strip().lstrip("\ufeff"): value
        for key, value in row.items()
        if key is not None and str(key).strip().lstrip("\ufeff") in _TSE_FIELDS
    }


def _decode_csv(payload: bytes) -> str:
    try:
        return payload.decode("utf-8-sig")
    except UnicodeDecodeError:
        return payload.decode("latin-1")


def _row_candidate(
    row: Mapping,
    default_election_year: int,
    archive_url: str | None,
) -> TSECandidate | None:
    row = _header_map(row)
    sq_candidato = _text(row.get("SQ_CANDIDATO"))
    full_name = _text(row.get("NM_CANDIDATO"))
    state = _text(row.get("SG_UF"))
    office = _text(row.get("DS_CARGO"))
    if not sq_candidato or not full_name or not state or not office:
        return None
    election_year = _text(row.get("ANO_ELEICAO"))
    try:
        year = int(election_year or default_election_year)
    except ValueError:
        year = default_election_year
    return TSECandidate(
        sq_candidato=sq_candidato,
        full_name=full_name,
        ballot_name=_text(row.get("NM_URNA_CANDIDATO")),
        state=state,
        office=office,
        party=_text(row.get("SG_PARTIDO")),
        raw_race=_text(row.get("DS_COR_RACA")),
        birth_date=parse_tse_date(row.get("DT_NASCIMENTO")),
        education=_text(row.get("DS_GRAU_INSTRUCAO")),
        occupation=_text(row.get("DS_OCUPACAO")),
        election_year=year,
        archive_url=archive_url,
    )


def parse_tse_date(value: object) -> date | None:
    value = _text(value)
    if value is None:
        return None
    for date_format in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value[:10], date_format).date()
        except ValueError:
            continue
    return None


def parse_tse_archive(
    payload: bytes,
    *,
    default_election_year: int = 2022,
    max_members: int = TSE_MAX_MEMBERS,
    max_uncompressed_bytes: int = TSE_MAX_UNCOMPRESSED_BYTES,
    max_member_bytes: int = TSE_MAX_MEMBER_BYTES,
    max_compression_ratio: int = TSE_MAX_COMPRESSION_RATIO,
    archive_url: str | None = None,
) -> list[TSECandidate]:
    candidates: list[TSECandidate] = []
    try:
        archive = ZipFile(io.BytesIO(payload))
    except BadZipFile as exc:
        raise ValueError("invalid TSE ZIP archive") from exc

    with archive:
        members = [info for info in archive.infolist() if not info.is_dir()]
        if len(members) > max_members:
            raise TSEArchiveLimitError("TSE archive has too many members")
        total_uncompressed = 0
        for info in members:
            if info.file_size > max_member_bytes:
                raise TSEArchiveLimitError("TSE archive member exceeds size limit")
            total_uncompressed += info.file_size
            if total_uncompressed > max_uncompressed_bytes:
                raise TSEArchiveLimitError("TSE archive exceeds uncompressed-size limit")
            if info.file_size and (
                info.compress_size == 0
                or info.file_size / info.compress_size > max_compression_ratio
            ):
                raise TSEArchiveLimitError("TSE archive member has unsafe compression ratio")
            if not info.filename.casefold().endswith(".csv"):
                continue
            try:
                content = archive.read(info)
                text = _decode_csv(content)
                rows = csv.DictReader(io.StringIO(text), delimiter=";")
                for row in rows:
                    try:
                        candidate = _row_candidate(row, default_election_year, archive_url)
                    except (TypeError, ValueError, UnicodeError):
                        candidate = None
                    if candidate is not None:
                        candidates.append(candidate)
            except (BadZipFile, OSError, RuntimeError, UnicodeError):
                continue
    return candidates


def _normalized(value: object) -> str:
    text = _text(value) or ""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", text.casefold()).strip()


def _normalized_name(value: object) -> str:
    return " ".join(_normalized(value).split())


def _normalized_office(value: object) -> str:
    return _normalized(value)


def _office_for_house(house: str) -> str | None:
    if house == "camara":
        return "deputado federal"
    if house == "senado":
        return "senador"
    return None


def _election_years_for_house(house: str) -> set[int]:
    if house == "camara":
        return {2022}
    if house == "senado":
        return {2018, 2022}
    return set()


def build_tse_index(candidates: Iterable[TSECandidate]) -> dict[tuple[str, str, str], list[TSECandidate]]:
    index = defaultdict(list)
    for candidate in candidates:
        index[
            (
                _normalized_office(candidate.office),
                _normalized_name(candidate.state),
                _normalized_name(candidate.full_name),
            )
        ].append(candidate)
    return dict(index)


def match_tse_candidate(
    index: Mapping[tuple[str, str, str], list[TSECandidate]],
    term: object,
) -> TSEMatch:
    office = _office_for_house(getattr(term, "house", ""))
    if office is None:
        return TSEMatch("unresolved")
    election_years = _election_years_for_house(getattr(term, "house", ""))
    parliamentarian = getattr(term, "parliamentarian", None)
    key = (
        _normalized_office(office),
        _normalized_name(getattr(term, "state", "")),
        _normalized_name(getattr(parliamentarian, "full_name", "")),
    )
    matches = [
        candidate
        for candidate in index.get(key, [])
        if candidate.election_year in election_years
    ]
    if not matches:
        return TSEMatch("unresolved")
    party_obj = getattr(term, "party", None)
    party = _normalized_name(getattr(party_obj, "acronym", ""))
    party_matches = [candidate for candidate in matches if _normalized_name(candidate.party) == party]
    if len(matches) == 1:
        return TSEMatch("matched", matches[0])
    if len(party_matches) == 1:
        return TSEMatch("matched", party_matches[0])
    return TSEMatch("ambiguous")


_RACE_LABELS = {
    "branca": "branca",
    "preta": "preta",
    "parda": "parda",
    "amarela": "amarela",
    "indigena": "indígena",
    "nao informado": "não informado",
    "nao declarada": "não informado",
    "sem informacao": "não informado",
    "ignorado": "não informado",
}


def normalize_race_label(value: object) -> str | None:
    return _RACE_LABELS.get(_normalized_name(value))
