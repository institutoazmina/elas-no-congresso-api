"""Orquestração da coleta diária via Celery.

Substitui run.sh + Scrapy + cron externo. Agendado pelo Celery Beat (ver settings).

Fluxo:
  ingest_camara / ingest_senado  (1 por casa, rodam em paralelo)
    └─ lista a janela diária
       └─ filtra por tema (assert_theme) ANTES dos saltos caros
          └─ busca detalhe + autores só do que é relevante
             └─ upsert idempotente (update_or_create) no domínio relacional
                └─ classify_proposition.delay(id)  (ML desacoplado — hoje só loga)
"""

import csv
import logging
import re
import unicodedata
from collections.abc import Mapping
from contextlib import ExitStack
from datetime import date, datetime, timedelta
from pathlib import Path

from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.legislatures.models import (
    Legislature,
    Parliamentarian,
    ParliamentarianProfileSource,
    ParliamentarianTerm,
    Party,
)
from apps.legislatures.services.profile_enrichment import upsert_source_profile
from apps.propositions.models import Proposition, PropositionAuthor, PropositionEvent
from apps.taxonomy.models import PropositionTheme, Theme

from .clients.camara import CamaraClient
from .clients.senado import SenadoClient
from .clients.tse import TSEClient
from .institutional_relationships import persist_official_relationships, persist_senado_fronts
from .mappers import (
    enrich_camara_author,
    map_camara_event,
    map_camara_proposition,
    map_senado_event,
    map_senado_proposition,
    parse_camara_authors,
    parse_senado_authors,
    parse_senado_authors_from_autoria,
    pick_senado_full_text_url,
)
from .models import IngestionRun
from .parliamentarians import normalize_camara_profile, normalize_senado_profile
from .resolvers import resolve_author
from .senado_fronts import scrape_senado_fronts
from .theme_assert import assert_theme
from .tse import build_tse_index, match_tse_candidate, normalize_race_label, parse_tse_archive

logger = logging.getLogger(__name__)


# ── persistência compartilhada ───────────────────────────────────────────────

def _persist(prop_kwargs: dict, event_kwargs: dict | None, authors: list[dict], temas: list[str]) -> int:
    """Upsert idempotente de uma proposição + evento + autores + temas.

    Retorna o pk da Proposition. Toda a escrita roda numa transação.
    """
    house = prop_kwargs["house"]
    external_id = prop_kwargs.pop("external_id")
    with transaction.atomic():
        prop, _ = Proposition.objects.update_or_create(
            house=house, external_id=external_id, defaults=prop_kwargs
        )

        if event_kwargs:
            PropositionEvent.objects.update_or_create(
                proposition=prop,
                event_at=event_kwargs.pop("event_at"),
                defaults=event_kwargs,
            )

        # Autores: substitui o conjunto a cada coleta (fonte da verdade é a API).
        prop.authors.all().delete()
        for a in authors:
            parl, inst = resolve_author(a, house)
            if not (parl or inst):
                continue
            party = None
            if a.get("party"):
                from apps.legislatures.models import Party

                sigla = a["party"].strip().upper()
                party, _ = Party.objects.get_or_create(
                    acronym=sigla, defaults={"name": sigla}
                )
            PropositionAuthor.objects.create(
                proposition=prop,
                parliamentarian=parl,
                institutional_author=inst,
                party=party,
                state_at_authorship=a.get("state"),
                order_index=a.get("order", 1),
            )

        # Temas detectados pelo regex de relevância.
        for rank, tema in enumerate(dict.fromkeys(t.strip() for t in temas if t), start=1):
            theme, _ = Theme.objects.get_or_create(
                slug=_slugify(tema), defaults={"name": tema.title()}
            )
            PropositionTheme.objects.update_or_create(
                proposition=prop, theme=theme, defaults={"rank": rank}
            )

    return prop.pk


def _slugify(value: str) -> str:
    import re
    import unicodedata

    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^\w\s-]", "", value).strip().lower()
    return re.sub(r"[\s_-]+", "-", value) or "tema"


def _daily_window() -> tuple[date, date]:
    """Janela ontem→amanhã, igual ao bot original (apanha fuso/atrasos)."""
    today = timezone.localdate()
    return today - timedelta(days=1), today + timedelta(days=1)


_PROFILE_ENRICHMENT_LOCK_KEY = "ingestion:parliamentarian-profile-enrichment"
_PROFILE_ENRICHMENT_LOCK_TIMEOUT = 60 * 60
_CAMARA_PROFILE_BASE_URL = "https://dadosabertos.camara.leg.br/api/v2"
_SENADO_PROFILE_BASE_URL = "https://legis.senado.leg.br/dadosabertos"
_PARLIAMENTARIANS_CSV = Path(__file__).resolve().parents[2] / "data" / "parlamentares.csv"
_IDENTITIES_CSV = Path(__file__).resolve().parents[2] / "data" / "parliamentarian_identities.csv"
_EXPECTED_CURRENT_ROSTER = {"camara": 513, "senado": 81}


class ReconciliationError(ValueError):
    """Official identity evidence is ambiguous or contradictory."""


def _current_profile_terms(today: date) -> list[ParliamentarianTerm]:
    """Return one stable term per current ``(house, external_id)`` identity."""
    terms = (
        ParliamentarianTerm.objects.filter(start_date__lte=today)
        .filter(Q(end_date__isnull=True) | Q(end_date__gte=today))
        .order_by("house", "external_id", "pk")
    )
    unique_terms = {}
    for term in terms:
        unique_terms.setdefault((term.house, term.external_id), term)
    return list(unique_terms.values())


def _profile_source_url(house: str, profile: dict, external_id: int, client) -> str:
    if house == "camara":
        base_url = getattr(client, "base_url", None) or _CAMARA_PROFILE_BASE_URL
        return profile.get("uri") or f"{base_url}/deputados/{external_id}"

    identification = profile.get("IdentificacaoParlamentar", {}) or {}
    return identification.get("UrlPaginaParlamentar") or (
        f"{getattr(client, 'base_url', None) or _SENADO_PROFILE_BASE_URL}/senador/{external_id}"
    )


def _empty_profile_enrichment_result(*, skipped: bool = False) -> dict:
    return {
        "skipped": skipped,
        "processed": 0,
        "failed": 0,
        "camara": {"processed": 0, "failed": 0},
        "senado": {"processed": 0, "failed": 0},
        "senado_fronts": {"processed": 0, "failed": 0, "memberships": 0},
        "tse": {"processed": 0, "unresolved": 0, "ambiguous": 0, "failed": 0},
        "terms": {
            "members": 0,
            "created": 0,
            "updated": 0,
            "failed": 0,
            "camara": {"members": 0, "created": 0, "updated": 0, "failed": 0},
            "senado": {"members": 0, "created": 0, "updated": 0, "failed": 0},
        },
    }


def _normalized_name(value: object) -> str:
    if value is None:
        return ""
    value = unicodedata.normalize("NFKD", str(value))
    value = "".join(char for char in value if not unicodedata.combining(char))
    value = re.sub(r"[^\w\s]", " ", value, flags=re.UNICODE)
    return " ".join(value.casefold().split())


def _text(value: object) -> str | None:
    if value is None:
        return None
    value = str(value).strip()
    return value or None


def _mapping(value: object) -> Mapping:
    return value if isinstance(value, Mapping) else {}


def _first_mapping(value: object) -> Mapping:
    if isinstance(value, list):
        return _mapping(value[0]) if value else {}
    return _mapping(value)


def _as_mappings(value: object) -> list[Mapping]:
    if isinstance(value, list):
        return [_mapping(item) for item in value]
    mapped = _mapping(value)
    return [mapped] if mapped else []


def _official_date(value: object) -> date | None:
    value = _text(value)
    if not value:
        return None
    for candidate in (value, value.split(" ", 1)[0]):
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            pass
        for fmt in ("%d/%m/%Y", "%d-%m-%Y"):
            try:
                return datetime.strptime(candidate, fmt).date()
            except ValueError:
                pass
    return None


def _legislature_numbers(value: object) -> set[int]:
    if isinstance(value, Mapping):
        for key in (
            "numero",
            "Numero",
            "numeroLegislatura",
            "NumeroLegislatura",
            "idLegislatura",
            "IdLegislatura",
        ):
            if key in value:
                return _legislature_numbers(value[key])
        return set()
    if isinstance(value, list):
        numbers = set()
        for item in value:
            numbers.update(_legislature_numbers(item))
        return numbers
    return {int(token) for token in re.findall(r"\d+", str(value))}


def _payload_legislature_numbers(member: Mapping, house: str) -> set[int]:
    if house == "camara":
        status = _mapping(member.get("ultimoStatus"))
        values = [member.get("idLegislatura"), status.get("idLegislatura")]
    else:
        mandate = _first_mapping(member.get("Mandato"))
        values = [
            mandate.get("NumeroLegislatura"),
            mandate.get("numeroLegislatura"),
            mandate.get("CodigoLegislatura"),
            mandate.get("Legislatura"),
            mandate.get("PrimeiraLegislaturaDoMandato"),
            mandate.get("SegundaLegislaturaDoMandato"),
        ]
    numbers = set()
    for value in values:
        numbers.update(_legislature_numbers(value))
    return numbers


def _senado_substitute_start(
    mandate: Mapping, *, today: date, fallback: date
) -> date:
    # Ordinary terms represent the legislature; only an active substitute
    # exercise has a reliable narrower start date in this payload.
    role = _normalized_name(
        mandate.get("DescricaoParticipacao") or mandate.get("TipoMandato")
    )
    if "suplente" not in role:
        return fallback

    exercises = _mapping(mandate.get("Exercicios"))
    candidates = []
    for exercise in _as_mappings(exercises.get("Exercicio")):
        start = _official_date(exercise.get("DataInicio"))
        if start is None or start > today:
            continue
        end = _official_date(exercise.get("DataFim"))
        if end is None or end >= today:
            candidates.append(start)
    return max(fallback, max(candidates, default=fallback))


def _integer(value: object) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"invalid official parliamentarian id: {value!r}") from None


def _member_fields(
    member: Mapping, house: str, *, legislature: Legislature, today: date
) -> dict:
    start_date = legislature.start_date
    if house == "camara":
        status = _mapping(member.get("ultimoStatus"))
        external_id = _integer(member.get("id") or status.get("id"))
        social_name = _text(
            member.get("nome")
            or member.get("nomeParlamentar")
            or status.get("nome")
            or status.get("nomeEleitoral")
        )
        full_name = _text(
            member.get("nomeCivil")
            or member.get("nomeCompleto")
            or member.get("nomeCompletoParlamentar")
        )
        party = member.get("siglaPartido") or member.get("partido")
        state = member.get("siglaUf") or member.get("uf")
        role = member.get("cargo") or member.get("tipo") or "Deputado"
    else:
        identification = _first_mapping(member.get("IdentificacaoParlamentar"))
        mandate = _first_mapping(member.get("Mandato"))
        external_id = _integer(identification.get("CodigoParlamentar"))
        social_name = _text(
            identification.get("NomeParlamentar")
            or identification.get("NomeSocialParlamentar")
        )
        full_name = _text(
            identification.get("NomeCompletoParlamentar")
            or identification.get("NomeCivilParlamentar")
        )
        party = (
            identification.get("SiglaPartidoParlamentar")
            or identification.get("SiglaPartido")
            or mandate.get("SiglaPartido")
        )
        state = identification.get("UfParlamentar") or identification.get("Uf")
        role = mandate.get("DescricaoParticipacao") or mandate.get("TipoMandato") or "Senador"
        start_date = _senado_substitute_start(
            mandate, today=today, fallback=legislature.start_date
        )

    party = _text(party)
    state = (_text(state) or "NI").upper()
    if len(state) > 2:
        state = state[:2]
    supplied_full_name = full_name
    social_name = social_name or full_name
    full_name = full_name or social_name
    if not full_name:
        raise ValueError(f"official member {external_id} has no name")
    return {
        "external_id": external_id,
        "full_name": full_name,
        "supplied_full_name": supplied_full_name,
        "social_name": social_name,
        "party": (party or "SEM PARTIDO").upper(),
        "state": state,
        "role": _text(role) or "Parlamentar",
        "start_date": start_date,
        "legislature_numbers": _payload_legislature_numbers(member, house),
    }


def _canonical_party_acronym(value: object) -> str:
    acronym = (_text(value) or "SEM PARTIDO").strip()
    folded = acronym.casefold()
    if folded == "pode":
        return "PODEMOS"
    if folded == "pcdob":
        return "PCdoB"
    return acronym.upper()


def _load_trusted_crosswalk() -> set[tuple[str, int, str]]:
    if not _PARLIAMENTARIANS_CSV.is_file():
        logger.warning("Crosswalk de parlamentares ausente: %s", _PARLIAMENTARIANS_CSV)
        return set()

    crosswalk = set()
    try:
        with _PARLIAMENTARIANS_CSV.open(encoding="utf-8", newline="") as source:
            for row in csv.DictReader(source):
                role = _normalized_name(row.get("cargo"))
                photo = (_text(row.get("foto")) or "").casefold()
                if "senador" in role and "camara.leg.br" in photo:
                    house = "camara"
                elif "senador" in role:
                    house = "senado"
                elif "deputado" in role:
                    house = "camara"
                else:
                    house = None
                name = _normalized_name(row.get("nome"))
                try:
                    external_id = int(row.get("numero", ""))
                except (TypeError, ValueError):
                    continue
                if house and name:
                    crosswalk.add((house, external_id, name))
    except OSError:
        logger.exception("Falha ao carregar crosswalk de parlamentares %s", _PARLIAMENTARIANS_CSV)
        return set()

    if not _IDENTITIES_CSV.is_file():
        logger.warning("Crosswalk de transições ausente: %s", _IDENTITIES_CSV)
        return crosswalk
    try:
        with _IDENTITIES_CSV.open(encoding="utf-8", newline="") as source:
            for row in csv.DictReader(source):
                name = _normalized_name(row.get("name"))
                if not name:
                    continue
                for house, column in (("camara", "camara_id"), ("senado", "senado_id")):
                    try:
                        external_id = int(row.get(column, ""))
                    except (TypeError, ValueError):
                        continue
                    crosswalk.add((house, external_id, name))
    except OSError:
        logger.exception("Falha ao carregar crosswalk de transições %s", _IDENTITIES_CSV)
    return crosswalk


class _BootstrapIndexes:
    """Indexes loaded once so member reconciliation never scans the full tables."""

    def __init__(self):
        self.term_people: dict[tuple[str, int], set[int]] = {}
        for row in ParliamentarianTerm.objects.values("house", "external_id", "parliamentarian_id"):
            self.term_people.setdefault((row["house"], row["external_id"]), set()).add(
                row["parliamentarian_id"]
            )

        self.source_people: dict[tuple[str, str], set[int]] = {}
        for row in ParliamentarianProfileSource.objects.filter(
            source__in=("camara", "senado")
        ).values("source", "source_key", "parliamentarian_id"):
            self.source_people.setdefault((row["source"], str(row["source_key"])), set()).add(
                row["parliamentarian_id"]
            )

        self.people_by_name: dict[str, set[int]] = {}
        for row in Parliamentarian.objects.values("id", "full_name", "social_name"):
            self.add_person(row["id"], row["full_name"], row["social_name"])

        self.crosswalk = _load_trusted_crosswalk()
        self.parties = {}
        for party in Party.objects.all():
            key = party.acronym.casefold()
            current = self.parties.get(key)
            if current is None or party.acronym in {"PCdoB", "PODEMOS"}:
                self.parties[key] = party

    def add_person(self, person_id: int, full_name: object, social_name: object) -> None:
        for name in (full_name, social_name):
            normalized = _normalized_name(name)
            if normalized:
                self.people_by_name.setdefault(normalized, set()).add(person_id)

    def add_term(self, term: ParliamentarianTerm) -> None:
        self.term_people.setdefault((term.house, term.external_id), set()).add(
            term.parliamentarian_id
        )

    def _evidence_person(self, *, house: str, external_id: int) -> int | None:
        term_ids = self.term_people.get((house, external_id))
        source_ids = self.source_people.get((house, str(external_id)))
        if term_ids is not None and len(term_ids) != 1:
            raise ReconciliationError(
                f"ambiguous term identity for {house}/{external_id}: {sorted(term_ids)}"
            )
        if source_ids is not None and len(source_ids) != 1:
            raise ReconciliationError(
                f"ambiguous profile identity for {house}/{external_id}: {sorted(source_ids)}"
            )
        term_id = next(iter(term_ids), None) if term_ids is not None else None
        source_id = next(iter(source_ids), None) if source_ids is not None else None
        if term_id is not None and source_id is not None and term_id != source_id:
            raise ReconciliationError(
                f"conflicting identities for {house}/{external_id}: {term_id} != {source_id}"
            )
        return term_id or source_id

    def resolve_person(self, *, house: str, external_id: int, fields: dict) -> int | None:
        evidence_id = self._evidence_person(house=house, external_id=external_id)
        if evidence_id is not None:
            return evidence_id

        for name in (fields["supplied_full_name"], fields["social_name"]):
            normalized = _normalized_name(name)
            if not normalized or (house, external_id, normalized) not in self.crosswalk:
                continue
            name_ids = self.people_by_name.get(normalized, set())
            return next(iter(name_ids)) if len(name_ids) == 1 else None
        return None

    def validate_existing_person(self, *, house: str, external_id: int, person_id: int) -> None:
        evidence_id = self._evidence_person(house=house, external_id=external_id)
        if evidence_id is not None and evidence_id != person_id:
            raise ReconciliationError(
                f"current term identity conflicts for {house}/{external_id}: "
                f"{person_id} != {evidence_id}"
            )

    def party(self, value: object) -> Party:
        acronym = _canonical_party_acronym(value)
        key = acronym.casefold()
        party = self.parties.get(key)
        if party is None:
            party = Party.objects.create(acronym=acronym, name=acronym)
            self.parties[key] = party
        return party


def _sync_current_member(
    *, house: str, fields: dict, legislature: Legislature, indexes: _BootstrapIndexes
) -> tuple[ParliamentarianTerm, bool]:
    with transaction.atomic():
        term = (
            ParliamentarianTerm.objects.select_for_update()
            .filter(
                house=house,
                external_id=fields["external_id"],
                legislature_number=legislature,
            )
            .first()
        )
        created = term is None
        if term is None:
            parliamentarian_id = indexes.resolve_person(
                house=house, external_id=fields["external_id"], fields=fields
            )
            if parliamentarian_id is None:
                parliamentarian = Parliamentarian.objects.create(
                    full_name=fields["full_name"], social_name=fields["social_name"]
                )
                parliamentarian_id = parliamentarian.pk
            party = indexes.party(fields["party"])
            term = ParliamentarianTerm.objects.create(
                parliamentarian_id=parliamentarian_id,
                legislature_number=legislature,
                party=party,
                house=house,
                role=fields["role"],
                state=fields["state"],
                external_id=fields["external_id"],
                start_date=fields["start_date"],
                end_date=None,
            )
            indexes.add_person(parliamentarian_id, fields["full_name"], fields["social_name"])
            indexes.add_term(term)
            return term, created

        indexes.validate_existing_person(
            house=house,
            external_id=fields["external_id"],
            person_id=term.parliamentarian_id,
        )
        term.party = indexes.party(fields["party"])
        term.role = fields["role"]
        term.state = fields["state"]
        term.end_date = None
        term.save(update_fields=["party", "role", "state", "end_date"])
        return term, created


def _close_absent_terms(
    *, house: str, legislature: Legislature, today: date, seen_external_ids: set[int]
) -> int:
    return ParliamentarianTerm.objects.filter(
        house=house,
        legislature_number=legislature,
        start_date__lt=today,
    ).filter(Q(end_date__isnull=True) | Q(end_date__gte=today)).exclude(
        external_id__in=seen_external_ids
    ).update(end_date=today - timedelta(days=1))


def _sync_current_terms_for_house(
    *, house: str, client, legislature: Legislature, today: date, result: dict, indexes
) -> None:
    list_members = getattr(client, "list_current_members", None)
    if list_members is None:
        return
    house_counts = result["terms"][house]
    seen_external_ids = set()
    member_failures = 0
    snapshot_failed = False
    snapshot_failure_counted = False
    try:
        members = []
        try:
            for member in list_members():
                members.append(member)
        except Exception:
            snapshot_failed = True
            snapshot_failure_counted = True
            result["terms"]["failed"] += 1
            house_counts["failed"] += 1
            logger.exception("Falha ao consumir roster atual da casa %s", house)

        parsed_members = []
        for member in members:
            try:
                fields = _member_fields(
                    _mapping(member), house, legislature=legislature, today=today
                )
                parsed_members.append((member, fields))
            except Exception:
                member_failures += 1
                result["terms"]["failed"] += 1
                house_counts["failed"] += 1
                logger.exception("Falha ao interpretar membro atual %s/%s", house, member)

        external_ids = [fields["external_id"] for _, fields in parsed_members]
        if (
            len(members) != _EXPECTED_CURRENT_ROSTER[house]
            or len(external_ids) != len(set(external_ids))
            or any(
                fields["legislature_numbers"]
                and legislature.number not in fields["legislature_numbers"]
                for _, fields in parsed_members
            )
        ):
            snapshot_failed = True

        if snapshot_failed and not snapshot_failure_counted:
            snapshot_failure_counted = True
            result["terms"]["failed"] += 1
            house_counts["failed"] += 1
            logger.warning(
                "Roster atual da casa %s rejeitado para reconciliação: size=%d expected=%d",
                house,
                len(members),
                _EXPECTED_CURRENT_ROSTER[house],
            )

        for member, fields in parsed_members:
            try:
                legislature_numbers = fields["legislature_numbers"]
                if legislature_numbers and legislature.number not in legislature_numbers:
                    logger.warning(
                        "Membro %s/%s ignorado: legislatura atual %s ausente de %s",
                        house,
                        fields["external_id"],
                        legislature.number,
                        sorted(legislature_numbers),
                    )
                    continue
                _, created = _sync_current_member(
                    house=house,
                    fields=fields,
                    legislature=legislature,
                    indexes=indexes,
                )
                seen_external_ids.add(fields["external_id"])
                result["terms"]["members"] += 1
                house_counts["members"] += 1
                field = "created" if created else "updated"
                result["terms"][field] += 1
                house_counts[field] += 1
            except Exception:
                member_failures += 1
                result["terms"]["failed"] += 1
                house_counts["failed"] += 1
                logger.exception("Falha ao sincronizar membro atual %s/%s", house, member)
    except Exception:
        member_failures += 1
        if not snapshot_failure_counted:
            result["terms"]["failed"] += 1
            house_counts["failed"] += 1
        logger.exception("Falha ao listar membros atuais da casa %s", house)
    else:
        if member_failures or snapshot_failed:
            return
        try:
            _close_absent_terms(
                house=house,
                legislature=legislature,
                today=today,
                seen_external_ids=seen_external_ids,
            )
        except Exception:
            result["terms"]["failed"] += 1
            house_counts["failed"] += 1
            logger.exception("Falha ao reconciliar termos ausentes da casa %s", house)


def _load_tse_index():
    candidates = []
    failed_archives = 0
    successful_archives = 0
    for election_year, archive_url in settings.TSE_CANDIDATES_ARCHIVE_URLS.items():
        try:
            with TSEClient(archive_url=archive_url) as client:
                archive = client.download_archive()
            candidates.extend(
                parse_tse_archive(
                    archive,
                    default_election_year=int(election_year),
                    archive_url=archive_url,
                )
            )
            successful_archives += 1
        except Exception:
            failed_archives += 1
            logger.exception(
                "Falha ao carregar arquivo oficial de candidaturas do TSE %s (%s)",
                election_year,
                archive_url,
            )

    if not successful_archives:
        return None, failed_archives
    return build_tse_index(candidates), failed_archives


def _load_senado_front_snapshot():
    with SenadoClient() as client:
        return scrape_senado_fronts(
            client,
            catalog_url=settings.SENADO_FRONT_CATALOG_URL,
            max_bytes=settings.SENADO_FRONT_MAX_BYTES,
            max_pages=settings.SENADO_FRONT_MAX_PAGES,
            max_fronts=settings.SENADO_FRONT_MAX_FRONTS,
            max_redirects=settings.SENADO_FRONT_MAX_REDIRECTS,
        )


def _persist_tse_race(term, index) -> str:
    match = match_tse_candidate(index, term)
    if match.status != "matched":
        return match.status

    candidate = match.candidate
    if candidate is None:
        return "failed"
    race = normalize_race_label(candidate.raw_race)
    upsert_source_profile(
        source="tse",
        source_key=candidate.sq_candidato,
        external_id=term.external_id,
        house=term.house,
        profile_values={"race": race} if race is not None else {},
        source_url=candidate.archive_url,
        metadata={
            "sq_candidato": candidate.sq_candidato,
            "raw_race": candidate.raw_race,
            "election_year": candidate.election_year,
            "term_external_id": term.external_id,
        },
    )
    return "processed"


@shared_task
def enrich_parliamentarian_profiles() -> dict:
    """Refresh current parliamentarian profiles from both official sources."""
    result = _empty_profile_enrichment_result()
    if not cache.add(
        _PROFILE_ENRICHMENT_LOCK_KEY,
        True,
        timeout=_PROFILE_ENRICHMENT_LOCK_TIMEOUT,
    ):
        result["skipped"] = True
        result["reason"] = "lock_held"
        return result

    try:
        today = timezone.localdate()
        legislature = Legislature.for_date(today)
        if legislature is None:
            raise RuntimeError(f"no current legislature found for {today.isoformat()}")

        tse_index = None
        try:
            tse_index, failed_archives = _load_tse_index()
            result["tse"]["failed"] += failed_archives
        except Exception:
            result["tse"]["failed"] += 1
            logger.exception("Falha ao carregar arquivo oficial de candidaturas do TSE")

        senado_front_snapshot = None
        try:
            senado_front_snapshot = _load_senado_front_snapshot()
            result["senado_fronts"]["failed"] += senado_front_snapshot.failed_fronts
            if senado_front_snapshot.failed_fronts:
                logger.warning(
                    "Falha ao carregar %d frente(s) parlamentare(s) do Senado",
                    senado_front_snapshot.failed_fronts,
                )
        except Exception:
            result["senado_fronts"]["failed"] += 1
            logger.exception("Falha ao carregar catálogo de frentes parlamentares do Senado")

        clients = {}
        indexes = _BootstrapIndexes()
        with ExitStack() as stack:
            for house, client_class in (
                ("camara", CamaraClient),
                ("senado", SenadoClient),
            ):
                try:
                    clients[house] = stack.enter_context(client_class())
                except Exception:
                    result["terms"]["failed"] += 1
                    result["terms"][house]["failed"] += 1
                    logger.exception("Falha ao abrir cliente da casa %s", house)

            for house in ("camara", "senado"):
                client = clients.get(house)
                if client is not None:
                    _sync_current_terms_for_house(
                        house=house,
                        client=client,
                        legislature=legislature,
                        today=today,
                        result=result,
                        indexes=indexes,
                    )

            current_terms = _current_profile_terms(today)
            if senado_front_snapshot is not None:
                try:
                    front_counts = persist_senado_fronts(
                        fronts=senado_front_snapshot.fronts,
                        terms=current_terms,
                    )
                    result["senado_fronts"]["processed"] += front_counts["processed"]
                    result["senado_fronts"]["failed"] += front_counts["failed"]
                    result["senado_fronts"]["memberships"] += front_counts["memberships"]
                except Exception:
                    result["senado_fronts"]["failed"] += 1
                    logger.exception("Falha ao persistir snapshot de frentes do Senado")

            for term in current_terms:
                house = term.house
                counts = result[house]
                try:
                    profile = clients[house].fetch_profile(term.external_id)
                    if house == "camara":
                        normalized = normalize_camara_profile(profile)
                    else:
                        normalized = normalize_senado_profile(profile)
                    upsert_source_profile(
                        source=house,
                        source_key=term.external_id,
                        house=house,
                        profile_values=normalized,
                        source_url=_profile_source_url(
                            house,
                            profile,
                            term.external_id,
                            clients[house],
                        ),
                    )
                    persist_official_relationships(term=term, client=clients[house])
                    counts["processed"] += 1
                except Exception:
                    counts["failed"] += 1
                    logger.exception(
                        "Falha ao enriquecer perfil %s/%s", house, term.external_id
                    )
                if tse_index is not None:
                    try:
                        tse_status = _persist_tse_race(term, tse_index)
                        result["tse"][tse_status] += 1
                    except Exception:
                        result["tse"]["failed"] += 1
                        logger.exception(
                            "Falha ao projetar raça autodeclarada do TSE %s/%s",
                            house,
                            term.external_id,
                        )

        result["processed"] = result["camara"]["processed"] + result["senado"]["processed"]
        result["failed"] = (
            result["camara"]["failed"]
            + result["senado"]["failed"]
            + result["terms"]["failed"]
        )
        return result
    finally:
        cache.delete(_PROFILE_ENRICHMENT_LOCK_KEY)


# ── Câmara ───────────────────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=2, default_retry_delay=300)
def ingest_camara(self):
    start, end = _daily_window()
    run = IngestionRun.objects.create(
        house="camara", window_start=start, window_end=end
    )
    try:
        with CamaraClient() as client:
            for summary in client.list_propositions(start, end):
                run.fetched_count += 1
                result = assert_theme(summary.get("ementa"))
                if not result["row_relevant"]:
                    continue
                run.relevant_count += 1
                try:
                    prop_id = int(summary["id"])
                    detail = client.fetch_detail(prop_id)
                    # Re-checa com ementa detalhada + keywords (mais sinal).
                    result = assert_theme(
                        summary.get("ementa"),
                        detail.get("ementaDetalhada"),
                        detail.get("keywords"),
                    )
                    if not result["row_relevant"]:  # pragma: no cover — defensivo
                        continue
                    authors = parse_camara_authors(client.fetch_authors(prop_id))
                    for author in authors:
                        if author["external_id"]:  # deputado → busca sexo/partido/UF
                            enrich_camara_author(author, client.fetch_deputy(author["external_id"]))
                    pk = _persist(
                        map_camara_proposition(summary, detail),
                        map_camara_event(detail),
                        authors,
                        result["temas"],
                    )
                    run.upserted_count += 1
                    classify_proposition.delay(pk)
                except Exception:
                    run.error_count += 1
                    logger.exception("Falha ao processar proposição Câmara %s", summary.get("id"))
        _finish(run, IngestionRun.Status.SUCCESS)
    except Exception as exc:
        _finish(run, IngestionRun.Status.FAILED, str(exc))
        raise self.retry(exc=exc) from exc
    return run.pk


# ── Senado ───────────────────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=2, default_retry_delay=300)
def ingest_senado(self):
    start, end = _daily_window()
    run = IngestionRun.objects.create(
        house="senado", window_start=start, window_end=end
    )
    try:
        with SenadoClient() as client:
            for summary in client.list_materias(end - timedelta(days=1)):
                run.fetched_count += 1
                result = assert_theme(summary.get("Ementa"))
                if not result["row_relevant"]:
                    continue
                run.relevant_count += 1
                try:
                    ident = summary.get("IdentificacaoMateria", {}) or {}
                    materia_id = int(ident.get("CodigoMateria") or summary["CodigoMateria"])
                    detail = client.fetch_detail(materia_id)
                    movements = client.fetch_movements(materia_id)
                    full_text_url = pick_senado_full_text_url(client.fetch_texts(materia_id))
                    # Autoria traz sexo/partido/UF; cai no texto livre se vazio.
                    authors = parse_senado_authors_from_autoria(
                        client.fetch_authors(materia_id)
                    ) or parse_senado_authors(detail, summary)
                    pk = _persist(
                        map_senado_proposition(summary, detail, full_text_url),
                        map_senado_event(movements),
                        authors,
                        result["temas"],
                    )
                    run.upserted_count += 1
                    classify_proposition.delay(pk)
                except Exception:
                    run.error_count += 1
                    logger.exception("Falha ao processar matéria Senado %s", summary)
        _finish(run, IngestionRun.Status.SUCCESS)
    except Exception as exc:
        _finish(run, IngestionRun.Status.FAILED, str(exc))
        raise self.retry(exc=exc) from exc
    return run.pk


def _finish(run: IngestionRun, status: str, error: str | None = None):
    run.status = status
    run.error_detail = error
    run.finished_at = timezone.now()
    run.save()
    logger.info(
        "Coleta %s %s: fetched=%d relevant=%d upserted=%d errors=%d",
        run.house, status, run.fetched_count, run.relevant_count,
        run.upserted_count, run.error_count,
    )


# ── classificação (ML) — TBD, hoje só loga ───────────────────────────────────

@shared_task
def classify_proposition(proposition_id: int):
    """Classificação (ML) — onde rodar o modelo está pendente (HF endpoint /
    fila dedicada / local). Por ora: prepara o inteiro teor (download + extração
    de texto do PDF) e apenas loga; a inferência em si é um stub.
    """
    prop = Proposition.objects.filter(pk=proposition_id).first()
    if not prop:
        logger.warning("[ML] proposição id=%s não encontrada", proposition_id)
        return

    full_text = None
    if prop.full_text_url:
        from .fulltext import extract_pdf_text

        full_text = extract_pdf_text(prop.full_text_url)
        if full_text:
            prop.full_text = full_text
            prop.save(update_fields=["full_text"])

    logger.info(
        "[ML pendente] classificar proposição id=%s %s — inteiro teor: %s chars",
        proposition_id,
        prop.number_label,
        len(full_text) if full_text else 0,
    )


# ── carga retroativa de anotações — JOB TEMPORÁRIO (remover após a carga) ─────

@shared_task(bind=True)
def backfill_annotations(self, reset: bool = True, start: int = 0, limit: int | None = None):
    """Carga retroativa das anotações humanas (one-shot, sequencial).

    Roda em processo no worker, gravando uma a uma (durável). Para retomar após
    queda, disparar de novo com ``start=<última linha>`` e ``reset=False``.
    """
    from scripts.load_annotations import run

    logger.info("[backfill] iniciando (reset=%s start=%s limit=%s)", reset, start, limit)
    stats = run(reset=reset, start=start, limit=limit)
    logger.info("[backfill] concluído: %s", stats)
    return stats
