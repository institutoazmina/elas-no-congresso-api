"""Public read model for legislative monitoring and celerity."""

from collections.abc import Iterable
from datetime import date, datetime
from hashlib import sha256

from django.core.cache import cache
from django.db.models import Q
from django.shortcuts import get_object_or_404
from ninja import Query, Router, Schema

from .celerity import calculate_celerity
from .explorer import (
    SOURCE_CACHE_KEY,
    DashboardRowSchema,
    ExplorerQuery,
    ExplorerSummarySchema,
    FilterOptionSchema,
    explore_activity,
    export_activity,
)
from .models import Proposition, PropositionAnalysis

router = Router()
ACTIVITY_CACHE_TIMEOUT = 5 * 60
FAST_CELERITY_LABELS = {"Rápida", "Tá voando"}
SLOW_CELERITY_LABELS = {"Lenta", "Travada"}
# Tipos legislativos que compõem o escopo editorial do Elas no Congresso.
# Não derivar a lista do texto de ``number_label``: a fonte oficial já fornece
# ``type_code`` normalizado e há documentos acessórios (REQ, SBT, pareceres)
# que não devem vazar para o painel.
PUBLIC_LEGISLATIVE_TYPES = {"PEC", "PL", "PLP", "PLV", "PDC", "PRC", "PLS", "PLN", "PRS", "PDS"}
PUBLIC_LEGISLATIVE_TYPE_CODES = PUBLIC_LEGISLATIVE_TYPES | {
    type_code.lower() for type_code in PUBLIC_LEGISLATIVE_TYPES
}
QUITERIA_ORGANIZATION_NAME = "QuitérIA"


def invalidate_activity_cache(propositions: Iterable[Proposition] = ()) -> None:
    """Expire every activity response after changing data it serializes."""
    delete_pattern = getattr(cache, "delete_pattern", None)
    if callable(delete_pattern):
        delete_pattern("activity:*")
    else:
        # LocMemCache used in tests does not implement ``delete_pattern``.
        for cache_key in (
            SOURCE_CACHE_KEY,
            "activity:list:5000",
            _activity_list_cache_key(5000, include_events=True),
            _activity_list_cache_key(5000, include_events=False),
            "activity:fast-unfavorable",
            "activity:slow-favorable",
        ):
            cache.delete(cache_key)
        for limit in range(1, 51):
            cache.delete(f"activity:enacted-projects:{limit}")

    for proposition in propositions:
        cache.delete(f"activity:proposition:{proposition.pk}")
        cache.delete(_public_identifier_cache_key(proposition.house, proposition.number_label))


class ActivityAuthorSchema(Schema):
    id: int | None = None
    name: str
    party: str | None = None
    state: str | None = None
    gender: str | None = None
    religion: str | None = None
    photo_url: str | None = None
    role: str | None = None


class ActivityEventSchema(Schema):
    event_at: datetime
    title: str | None = None
    description: str | None = None
    url: str | None = None
    situation: str | None = None
    committee_acronym: str | None = None
    committee_name: str | None = None


class CeleritySchema(Schema):
    label: str
    days_without_movement: int
    movements_last_90_days: int
    last_event_at: datetime | None = None


class ActivityPropositionSchema(Schema):
    id: int
    house: str
    number_label: str
    ementa: str
    presented_at: date
    current_status: str | None = None
    tramitation_url: str | None = None
    category: str | None = None
    category_label: str | None = None
    themes: list[str]
    is_favorable: bool | None = None
    assessment_organization: str | None = None
    assessment_comments: str | None = None
    relevance: str | None = None
    authors: list[ActivityAuthorSchema]
    celerity: CeleritySchema
    events: list[ActivityEventSchema]


class EnactmentSchema(Schema):
    status_code: int
    status: str
    law_label: str
    law_type: str
    law_number: int
    law_year: int
    enacted_at: date


class ActivityExplorerSchema(Schema):
    items: list[ActivityPropositionSchema]
    total: int
    page: int
    page_count: int
    options: dict[str, list[FilterOptionSchema]]
    summary: ExplorerSummarySchema
    dashboard: dict[str, list[DashboardRowSchema]]


class EnactedProjectSchema(ActivityPropositionSchema):
    assessment_label: str
    enactment: EnactmentSchema


def _selected_annotation(proposition):
    annotations = list(proposition.annotations.all())
    return next((annotation for annotation in annotations if annotation.is_favorable is False), None) or next(
        (annotation for annotation in annotations if annotation.is_favorable is True), None
    ) or (annotations[0] if annotations else None)


def _serialize(proposition, *, event_limit: int | None) -> dict:
    events = sorted(proposition.events.all(), key=lambda event: event.event_at, reverse=True)
    annotation = _selected_annotation(proposition)
    analysis = getattr(proposition, "analysis", None)
    authors = []
    for author in proposition.authors.all():
        person = author.parliamentarian
        institutional = author.institutional_author
        authors.append(
            {
                "id": person.pk if person else None,
                "name": person.social_name or person.full_name if person else institutional.name,
                "party": author.party.acronym if author.party else None,
                "state": author.state_at_authorship,
                "gender": person.gender if person else None,
                "religion": person.religion if person else None,
                "photo_url": person.photo_url if person else None,
                "role": None,
            }
        )
    celerity = calculate_celerity(proposition, events)
    shown_events = events[:event_limit] if event_limit is not None else events
    category = annotation.category if annotation else getattr(analysis, "theme_category", None)
    # A anotação humana sempre prevalece. Na sua ausência, uma classificação
    # concluída pela QuitérIA é a avaliação automática exibida no painel.
    has_quiteria_assessment = (
        annotation is None
        and analysis is not None
        and analysis.analysis_status == PropositionAnalysis.Status.SUCCEEDED
        and analysis.classification in (0, 1)
    )
    # O rótulo editorial vem da enumeração de categorias, sem transformar o
    # slug em texto aproximado no cliente.
    from apps.core.enums import PropositionCategory

    category_label = dict(PropositionCategory.choices).get(category, category) if category else None

    return {
        "id": proposition.pk,
        # Internal explorer metadata distinguishes PL coauthorship semantics.
        "type_code": proposition.type_code,
        "house": proposition.house,
        "number_label": proposition.number_label,
        "ementa": proposition.ementa,
        "presented_at": proposition.presented_at,
        "current_status": proposition.current_status,
        "tramitation_url": proposition.tramitation_url,
        "category": category,
        "category_label": category_label,
        "themes": [
            relation.theme.name
            for relation in proposition.proposition_themes.all()
        ],
        "is_favorable": (
            annotation.is_favorable
            if annotation
            else (analysis.classification == 0 if has_quiteria_assessment else None)
        ),
        "assessment_organization": (
            annotation.organization.name
            if annotation
            else (QUITERIA_ORGANIZATION_NAME if has_quiteria_assessment else None)
        ),
        "assessment_comments": annotation.comments if annotation else None,
        "relevance": annotation.relevance if annotation else None,
        "authors": authors,
        "celerity": {
            "label": celerity.label,
            "days_without_movement": celerity.days_without_movement,
            "movements_last_90_days": celerity.movements_last_90_days,
            "last_event_at": celerity.last_event_at,
        },
        "events": [
            {
                "event_at": event.event_at,
                "title": event.title or event.description,
                "description": event.dispatch or event.description,
                "url": event.raw_payload.get("url") if event.raw_payload else None,
                "situation": event.situation,
                "committee_acronym": event.committee_acronym,
                "committee_name": event.committee_name,
            }
            for event in shown_events
        ],
    }


def _law_label(proposition: Proposition) -> str:
    number = f"{proposition.enacted_law_number:,}".replace(",", ".")
    return f"{proposition.enacted_law_type} {number}/{proposition.enacted_law_year}"


def _serialize_enacted(proposition: Proposition) -> dict:
    activity = _serialize(proposition, event_limit=0)
    activity["assessment_label"] = "favorável" if activity["is_favorable"] else "desfavorável"
    activity["enactment"] = {
        "status_code": proposition.current_status_code,
        "status": proposition.current_status,
        "law_label": _law_label(proposition),
        "law_type": proposition.enacted_law_type,
        "law_number": proposition.enacted_law_number,
        "law_year": proposition.enacted_law_year,
        "enacted_at": proposition.enacted_at,
    }
    return activity


def _queryset():
    return Proposition.objects.filter(
        is_approved=True,
        type_code__in=PUBLIC_LEGISLATIVE_TYPE_CODES,
    ).select_related("analysis").prefetch_related(
        "events",
        "annotations__organization",
        "authors__parliamentarian",
        "authors__institutional_author",
        "authors__party",
        "proposition_themes__theme",
    )


def _cached_activity(proposition_id: int) -> dict | None:
    return cache.get(f"activity:proposition:{proposition_id}")


def _cache_activity(proposition_id: int, activity: dict) -> dict:
    cache.set(f"activity:proposition:{proposition_id}", activity, ACTIVITY_CACHE_TIMEOUT)
    return activity


def _cache_activity_collection(cache_key: str, activity: list[dict]) -> list[dict]:
    cache.set(cache_key, activity, ACTIVITY_CACHE_TIMEOUT)
    return activity


def _activity_list_cache_key(limit: int, *, include_events: bool) -> str:
    return f"activity:list:{limit}:events:{int(include_events)}"


def _activity_for_proposition(proposition_id: int) -> dict:
    cached = _cached_activity(proposition_id)
    if cached is not None:
        return cached

    proposition = get_object_or_404(_queryset(), pk=proposition_id)
    return _cache_activity(proposition_id, _serialize(proposition, event_limit=None))


def _public_identifier_cache_key(house: str, number_label: str) -> str:
    identifier = f"{house.strip().lower()}:{number_label.strip().upper()}"
    return f"activity:public:{sha256(identifier.encode()).hexdigest()}"


@router.get("", response=list[ActivityPropositionSchema])
def list_activity(request, limit: int = 5000, include_events: bool = True):
    """All monitored proposals; event history is optional for compact listings."""
    limit = min(max(limit, 1), 5000)
    cache_key = _activity_list_cache_key(limit, include_events=include_events)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    event_limit = 5 if include_events else 0
    activity = [_serialize(proposition, event_limit=event_limit) for proposition in _queryset().order_by("-presented_at")[:limit]]
    cache.set(cache_key, activity, ACTIVITY_CACHE_TIMEOUT)
    return activity


@router.get("/fast-unfavorable", response=list[ActivityPropositionSchema])
def list_fast_unfavorable_activity(request):
    """Todas as desfavoráveis com tramitação rápida e movimentos nos últimos 90 dias."""
    cache_key = "activity:fast-unfavorable"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    activity = []
    propositions = _queryset().filter(annotations__is_favorable=False).distinct()
    for proposition in propositions:
        serialized = _serialize(proposition, event_limit=0)
        if (
            serialized["celerity"]["label"] in FAST_CELERITY_LABELS
            and serialized["celerity"]["movements_last_90_days"] > 0
        ):
            activity.append(serialized)

    activity.sort(
        key=lambda item: (
            item["celerity"]["label"] == "Tá voando",
            item["celerity"]["movements_last_90_days"],
        ),
        reverse=True,
    )
    return _cache_activity_collection(cache_key, activity)


@router.get("/slow-favorable", response=list[ActivityPropositionSchema])
def list_slow_favorable_activity(request):
    """As 50 favoráveis mais paradas, sem incluir as esquecidas."""
    cache_key = "activity:slow-favorable"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    activity = []
    propositions = _queryset().filter(annotations__is_favorable=True).distinct()
    for proposition in propositions:
        serialized = _serialize(proposition, event_limit=0)
        if serialized["celerity"]["label"] in SLOW_CELERITY_LABELS:
            activity.append(serialized)

    activity.sort(key=lambda item: item["celerity"]["days_without_movement"], reverse=True)
    return _cache_activity_collection(cache_key, activity[:50])


@router.get("/enacted-projects", response=list[EnactedProjectSchema])
def list_enacted_projects(request, limit: int = 50):
    """Up to 50 assessed propositions officially transformed into a complete law."""
    limit = min(max(limit, 1), 50)
    cache_key = f"activity:enacted-projects:{limit}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    enacted_statuses = Q(house="camara", current_status_code=1140) | Q(
        house="senado", current_status_code__in=(64, 92)
    )
    propositions = (
        _queryset()
        .filter(enacted_statuses, annotations__is_favorable__isnull=False)
        .filter(
            enacted_law_type__isnull=False,
            enacted_law_number__isnull=False,
            enacted_law_year__isnull=False,
            enacted_at__isnull=False,
        )
        .distinct()
        .order_by("-enacted_at", "-pk")[:limit]
    )
    return _cache_activity_collection(
        cache_key,
        [_serialize_enacted(proposition) for proposition in propositions],
    )


@router.get("/by-number", response=ActivityPropositionSchema)
def get_activity_by_number(request, house: str, number_label: str):
    """Full activity for the public proposition identifier used by the site."""
    cache_key = _public_identifier_cache_key(house, number_label)
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    proposition = get_object_or_404(
        Proposition.objects.only("pk"),
        house=house.strip().lower(),
        number_label__iexact=number_label.strip(),
    )
    activity = _activity_for_proposition(proposition.pk)
    cache.set(cache_key, activity, ACTIVITY_CACHE_TIMEOUT)
    return activity


@router.get("/explorer", response=ActivityExplorerSchema)
def get_activity_explorer(request, filters: ExplorerQuery = Query(...)):
    """API-owned filtering, available options and statistics over all public proposals."""
    return explore_activity(filters)


@router.get("/explorer/export")
def get_activity_explorer_export(request, filters: ExplorerQuery = Query(...)):
    """Export the full filtered collection, independently of the displayed page."""
    return export_activity(filters)


@router.get("/{proposition_id}", response=ActivityPropositionSchema)
def get_activity(request, proposition_id: int):
    return _activity_for_proposition(proposition_id)
