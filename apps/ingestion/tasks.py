"""Durable daily activity ingestion; substantive documents and AI use the ML queue."""

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
from apps.propositions.models import (
    Proposition,
    PropositionAuthor,
    PropositionEvent,
)
from apps.taxonomy.models import PropositionTheme, Theme

from .clients.camara import CamaraClient
from .clients.senado import SenadoClient
from .clients.tse import TSEClient
from .institutional_relationships import persist_official_relationships, persist_senado_fronts
from .mappers import (
    map_camara_enactment,
    map_camara_events,
    map_camara_proposition,
    map_senado_enactment,
    map_senado_process_events,
    map_senado_process_status,
)
from .models import IngestionRun
from .parliamentarians import normalize_camara_profile, normalize_senado_profile
from .resolvers import resolve_author
from .senado_fronts import scrape_senado_fronts
from .tse import build_tse_index, match_tse_candidate, normalize_race_label, parse_tse_archive

logger = logging.getLogger(__name__)


# ── persistência compartilhada ───────────────────────────────────────────────


def _persist(
    prop_kwargs: dict,
    event_kwargs: dict | list[dict] | None,
    authors: list[dict] | None,
    temas: list[str],
) -> int:
    """Upsert idempotente de uma proposição + histórico + autores + temas.

    Retorna o pk da Proposition. Toda a escrita roda numa transação.
    """
    prop_kwargs = prop_kwargs.copy()
    house = prop_kwargs["house"]
    external_id = prop_kwargs.pop("external_id")
    with transaction.atomic():
        prop, created = Proposition.objects.select_for_update(of=("self",)).get_or_create(
            house=house, external_id=external_id, defaults=prop_kwargs
        )
        old_ementa = prop.ementa
        if not created:
            prop_kwargs.pop("is_approved", None)
            if not prop_kwargs.get("full_text_url") and prop.full_text_url:
                prop_kwargs.pop("full_text_url", None)
            payload = prop_kwargs.get("raw_payload")
            if house == "senado" and payload is not None and not payload.get("_senado_process_id"):
                payload["_senado_process_id"] = (prop.raw_payload or {}).get("_senado_process_id")
            changed = {k: v for k, v in prop_kwargs.items() if getattr(prop, k) != v}
            if changed:
                Proposition.objects.filter(pk=prop.pk).update(**changed, updated_at=timezone.now())
                for key, value in changed.items():
                    setattr(prop, key, value)
        Proposition.objects.filter(pk=prop.pk).update(source_checked_at=timezone.now())

        _persist_events(prop, event_kwargs)

        author_rows = []
        for a in authors or []:
            parl, inst = resolve_author(a, house)
            if not (parl or inst):
                continue
            party = None
            if a.get("party"):
                from apps.legislatures.models import Party

                sigla = a["party"].strip().upper()
                party, _ = Party.objects.get_or_create(acronym=sigla, defaults={"name": sigla})
            author_rows.append(
                {
                    "parliamentarian_id": parl.pk if parl else None,
                    "institutional_author_id": inst.pk if inst else None,
                    "party_id": party.pk if party else None,
                    "state_at_authorship": a.get("state"),
                    "order_index": a.get("order", 1),
                }
            )
        if authors is not None:
            fields = [
                "parliamentarian_id",
                "institutional_author_id",
                "party_id",
                "state_at_authorship",
                "order_index",
            ]
            current_authors = list(prop.authors.order_by("order_index", "pk").values(*fields))
            if current_authors != author_rows:
                prop.authors.all().delete()
                PropositionAuthor.objects.bulk_create(
                    [PropositionAuthor(proposition=prop, **row) for row in author_rows]
                )

        # Temas detectados pelo regex de relevância.
        for rank, tema in enumerate(dict.fromkeys(t.strip() for t in temas if t), start=1):
            theme, _ = Theme.objects.get_or_create(
                slug=_slugify(tema), defaults={"name": tema.title()}
            )
            link, link_created = PropositionTheme.objects.get_or_create(
                proposition=prop, theme=theme, defaults={"rank": rank}
            )
            if not link_created and link.rank != rank:
                PropositionTheme.objects.filter(pk=link.pk).update(rank=rank)

        from .content import register_fallback

        register_fallback(
            prop.pk,
            analyze=not prop.full_text_url
            and (created or (not prop.full_text and old_ementa != prop.ementa)),
        )

    return prop.pk


def _persist_events(prop: Proposition, event_kwargs: dict | list[dict] | None) -> None:
    """Upsert source events without rewriting proposition metadata or authors."""
    events = [e for e in (event_kwargs if isinstance(event_kwargs, list) else [event_kwargs]) if e]
    if not events:
        return
    with transaction.atomic():
        Proposition.objects.select_for_update(of=("self",)).get(pk=prop.pk)
        current = list(prop.events.order_by("pk"))
        by_source = {e.source_event_id: e for e in current if e.source_event_id}
        legacy = {e.event_at: e for e in reversed(current) if not e.source_event_id}
        new, changed, fields = [], {}, set()
        for values in events:
            values = values.copy()
            key, at = values.get("source_event_id"), values["event_at"]
            existing = by_source.get(key) if key else legacy.get(at)
            if existing is None and key:
                existing = legacy.pop(at, None)
            if existing is None:
                existing = PropositionEvent(proposition=prop, **values)
                new.append(existing)
            else:
                edits = {k: v for k, v in values.items() if getattr(existing, k) != v}
                for field, value in edits.items():
                    setattr(existing, field, value)
                if edits and existing.pk:
                    changed[existing.pk] = existing
                    fields.update(edits)
            if key:
                by_source[key] = existing
            else:
                legacy[at] = existing
        PropositionEvent.objects.bulk_create(new)
        if changed:
            PropositionEvent.objects.bulk_update(list(changed.values()), sorted(fields))


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


def _senado_substitute_start(mandate: Mapping, *, today: date, fallback: date) -> date:
    # Ordinary terms represent the legislature; only an active substitute
    # exercise has a reliable narrower start date in this payload.
    role = _normalized_name(mandate.get("DescricaoParticipacao") or mandate.get("TipoMandato"))
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


def _member_fields(member: Mapping, house: str, *, legislature: Legislature, today: date) -> dict:
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
            identification.get("NomeParlamentar") or identification.get("NomeSocialParlamentar")
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
        start_date = _senado_substitute_start(mandate, today=today, fallback=legislature.start_date)

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
    return (
        ParliamentarianTerm.objects.filter(
            house=house,
            legislature_number=legislature,
            start_date__lt=today,
        )
        .filter(Q(end_date__isnull=True) | Q(end_date__gte=today))
        .exclude(external_id__in=seen_external_ids)
        .update(end_date=today - timedelta(days=1))
    )


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


def _optional_profile_collection(client, method_name: str, external_id: int) -> list[dict]:
    method = getattr(client, method_name, None)
    if method is None:
        return []
    try:
        return method(external_id)
    except Exception:
        logger.exception(
            "Falha ao carregar campo complementar %s/%s",
            method_name,
            external_id,
        )
        return []


def _persist_tse_profile(term, index) -> str:
    match = match_tse_candidate(index, term)
    if match.status != "matched":
        return match.status

    candidate = match.candidate
    if candidate is None:
        return "failed"
    race = normalize_race_label(candidate.raw_race)
    profile_values = {
        "birth_date": candidate.birth_date,
        "race": race,
        "education": candidate.education,
        "profession": candidate.occupation,
    }
    upsert_source_profile(
        source="tse",
        source_key=candidate.sq_candidato,
        external_id=term.external_id,
        house=term.house,
        profile_values={key: value for key, value in profile_values.items() if value is not None},
        source_url=candidate.archive_url,
        metadata={
            "sq_candidato": candidate.sq_candidato,
            "raw_race": candidate.raw_race,
            "raw_education": candidate.education,
            "raw_occupation": candidate.occupation,
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
                        professions = _optional_profile_collection(
                            clients[house],
                            "fetch_deputy_professions",
                            term.external_id,
                        )
                        normalized = normalize_camara_profile(
                            profile,
                            professions=professions,
                        )
                    else:
                        professions = _optional_profile_collection(
                            clients[house],
                            "fetch_senator_professions",
                            term.external_id,
                        )
                        academic_history = _optional_profile_collection(
                            clients[house],
                            "fetch_senator_academic_history",
                            term.external_id,
                        )
                        normalized = normalize_senado_profile(
                            profile,
                            professions=professions,
                            academic_history=academic_history,
                        )
                    upsert_source_profile(
                        source=house,
                        source_key=term.external_id,
                        house=house,
                        profile_values={
                            key: value
                            for key, value in normalized.items()
                            if value is not None
                            or key not in {"birth_date", "education", "profession"}
                        },
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
                    logger.exception("Falha ao enriquecer perfil %s/%s", house, term.external_id)
                if tse_index is not None:
                    try:
                        tse_status = _persist_tse_profile(term, tse_index)
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
            result["camara"]["failed"] + result["senado"]["failed"] + result["terms"]["failed"]
        )
        return result
    finally:
        cache.delete(_PROFILE_ENRICHMENT_LOCK_KEY)


# ── Câmara ───────────────────────────────────────────────────────────────────


@shared_task(bind=True, max_retries=2, default_retry_delay=300)
def ingest_camara(self):
    from .sync import begin_daily

    return begin_daily("camara", CamaraClient)


@shared_task(bind=True, max_retries=2, default_retry_delay=300)
def ingest_senado(self):
    from .sync import begin_daily

    return begin_daily("senado", SenadoClient)


@shared_task
def sync_daily_batch(run_id):
    from .sync import process_batch

    run = IngestionRun.objects.get(pk=run_id)
    key = f"ingestion:batch:{run_id}"
    if not cache.add(key, True, timeout=1800):
        return
    try:
        try:
            more = process_batch(run_id, CamaraClient if run.house == "camara" else SenadoClient)
        except Exception as exc:
            run.error_detail = f"Batch interrupted ({type(exc).__name__}); pending items preserved"
            run.save(update_fields=["error_detail"])
            logger.warning("Ingestion run %s batch interrupted (%s)", run_id, type(exc).__name__)
            return
    finally:
        cache.delete(key)
    if more:
        sync_daily_batch.apply_async(args=[run_id], countdown=5)


@shared_task(queue="ml")
def check_proposition_document(document_id):
    from .content import check_document

    return check_document(document_id)


@shared_task(queue="ml")
def run_classification_request(request_id):
    from .content import run_analysis

    return run_analysis(request_id)


@shared_task
def recover_pending_content():
    from apps.propositions.models import ClassificationRequest, PropositionDocument

    for run_id in IngestionRun.objects.filter(
        status="running", discovery_complete=True
    ).values_list("pk", flat=True):
        sync_daily_batch.delay(run_id)
    stale = timezone.now() - timedelta(minutes=90)
    for pk in PropositionDocument.objects.filter(
        Q(status__in=["pending", "failed"], attempts__lt=3)
        | Q(status="fetching", attempted_at__lt=stale, attempts__lt=3)
    ).values_list("pk", flat=True)[:100]:
        check_proposition_document.delay(pk)
    for pk in ClassificationRequest.objects.filter(
        Q(status__in=["pending", "failed"], attempts__lt=3)
        | Q(status="running", attempted_at__lt=stale, attempts__lt=3)
    ).values_list("pk", flat=True)[:100]:
        run_classification_request.delay(pk)


@shared_task
def reconcile_daily_propositions(full_baseline=False):
    key = "ingestion:reconcile-discovery"
    if not cache.add(key, True, timeout=1800):
        return
    try:
        return _reconcile_daily_propositions(full_baseline)
    finally:
        cache.delete(key)


def _reconcile_daily_propositions(full_baseline):
    from .models import IngestionCheckpoint, IngestionItem

    cutoff = timezone.now() - timedelta(days=7)
    for house in ("camara", "senado"):
        checkpoint, _ = IngestionCheckpoint.objects.get_or_create(house=house)
        pending = IngestionRun.objects.filter(
            house=house, kind="reconcile", status="running"
        ).first()
        if pending and pending.status != "success":
            pending.items.filter(status="failed").update(status="pending", attempts=0)
            pending.status = pending.Status.RUNNING
            pending.save(update_fields=["status"])
            sync_daily_batch.delay(pending.pk)
            continue
        targets = list(
            Proposition.objects.filter(house=house)
            .filter(Q(reconciled_at__isnull=True) | Q(reconciled_at__lt=cutoff))
            .order_by("reconciled_at", "pk")[
                : 100000
                if full_baseline and not checkpoint.baseline_complete
                else settings.INGESTION_RECONCILIATION_DAILY_LIMIT
            ]
        )
        if not targets:
            checkpoint.baseline_complete = True
            checkpoint.save(update_fields=["baseline_complete", "updated_at"])
            continue
        run = IngestionRun.objects.create(
            house=house,
            kind="reconcile",
            window_start=timezone.localdate() - timedelta(days=7),
            window_end=timezone.localdate() + timedelta(days=1),
            discovery_complete=True,
            fetched_count=len(targets),
            checkpoint_until=timezone.now(),
        )
        IngestionItem.objects.bulk_create(
            [
                IngestionItem(
                    run=run,
                    external_id=p.external_id,
                    summary={
                        "id": p.external_id,
                        "ementa": p.ementa,
                        "Ementa": p.ementa,
                        "IdentificacaoMateria": {
                            "CodigoMateria": p.external_id,
                            "IdentificacaoProcesso": (p.raw_payload or {}).get(
                                "_senado_process_id"
                            ),
                        },
                    },
                )
                for p in targets
            ]
        )
        sync_daily_batch.delay(run.pk)


def _finish(run: IngestionRun, status: str, error: str | None = None):
    run.status = status
    run.error_detail = error
    run.finished_at = timezone.now()
    run.save()
    logger.info(
        "Coleta %s %s: fetched=%d relevant=%d upserted=%d errors=%d",
        run.house,
        status,
        run.fetched_count,
        run.relevant_count,
        run.upserted_count,
        run.error_count,
    )


# ── atualização de promulgações ──────────────────────────────────────────────

_ENACTMENT_FIELDS = (
    "enacted_law_type",
    "enacted_law_number",
    "enacted_law_year",
    "enacted_at",
)


def _enactment_fields(enactment: dict | None) -> dict:
    return enactment or dict.fromkeys(_ENACTMENT_FIELDS)


def refresh_enacted_propositions(queryset=None) -> dict:
    """Refresh official statuses for every proposition with a human assessment.

    The daily Senate listing excludes closed matters, so this refresh follows the
    saved process identifier instead of relying on ``/materia/tramitando``.
    """
    if queryset is None:
        queryset = (
            Proposition.objects.filter(annotations__is_favorable__isnull=False)
            .distinct()
            .order_by("pk")
        )

    stats = {"processed": 0, "enacted": 0, "events": 0, "failed": 0}
    changed = []
    with CamaraClient() as camara, SenadoClient() as senado:
        for proposition in queryset:
            try:
                if proposition.house == "camara":
                    detail = camara.fetch_detail(proposition.external_id)
                    tramitations = camara.fetch_tramitations(proposition.external_id)
                    fields = map_camara_proposition({}, detail)
                    fields = {
                        "current_status": fields["current_status"],
                        "current_status_code": fields["current_status_code"],
                        "is_active": fields.get("is_active", proposition.is_active),
                        **_enactment_fields(map_camara_enactment(detail, tramitations)),
                    }
                    events = map_camara_events(tramitations)
                else:
                    process_id = (proposition.raw_payload or {}).get("_senado_process_id")
                    if not process_id:
                        logger.warning(
                            "Matéria Senado sem processo: proposition=%s", proposition.pk
                        )
                        stats["failed"] += 1
                        continue
                    process = senado.fetch_process(int(process_id))
                    fields = {
                        **map_senado_process_status(process),
                        **_enactment_fields(map_senado_enactment(process)),
                    }
                    events = map_senado_process_events(process)

                with transaction.atomic():
                    for field, value in fields.items():
                        setattr(proposition, field, value)
                    proposition.save(update_fields=[*fields, "updated_at"])
                    _persist_events(proposition, events)

                stats["processed"] += 1
                stats["events"] += len(events)
                if fields["enacted_at"]:
                    stats["enacted"] += 1
                changed.append(proposition)
            except Exception:
                stats["failed"] += 1
                logger.exception("Falha ao atualizar promulgação da proposição %s", proposition.pk)

    if changed:
        from apps.propositions.activity import invalidate_activity_cache

        invalidate_activity_cache(changed)
    return stats


@shared_task
def refresh_enacted_proposition_statuses() -> dict:
    """Compatibility with the retired full-assessment refresh schedule."""
    task = reconcile_daily_propositions.delay()
    return {"queued": str(task.id)}


# ── classificação (QuitérIA 2.0) ─────────────────────────────────────────────


@shared_task(queue="ml")
def classify_proposition(proposition_id: int):
    """Explicit maintenance entry point; daily status changes do not call this task."""
    from .content import register_document, register_fallback, request_analysis

    prop = Proposition.objects.filter(pk=proposition_id).first()
    if prop is None:
        return
    register_fallback(prop.pk, analyze=True)
    if prop.full_text_url:
        register_document(prop.pk, "original", "original", prop.full_text_url)
    with transaction.atomic():
        prop = Proposition.objects.select_for_update(of=("self",)).get(pk=proposition_id)
        if prop.current_content_id:
            request_analysis(prop, prop.current_content)


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
