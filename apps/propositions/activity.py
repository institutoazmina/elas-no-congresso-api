"""Public read model for legislative monitoring and celerity."""

from datetime import date, datetime
from hashlib import sha256

from django.core.cache import cache
from django.shortcuts import get_object_or_404
from ninja import Router, Schema

from .celerity import calculate_celerity
from .models import Proposition

router = Router()
ACTIVITY_CACHE_TIMEOUT = 5 * 60


class ActivityAuthorSchema(Schema):
    id: int | None = None
    name: str
    party: str | None = None
    state: str | None = None
    gender: str | None = None
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
    is_favorable: bool | None = None
    assessment_organization: str | None = None
    assessment_comments: str | None = None
    relevance: str | None = None
    authors: list[ActivityAuthorSchema]
    celerity: CeleritySchema
    events: list[ActivityEventSchema]


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
                "photo_url": person.photo_url if person else None,
                "role": None,
            }
        )
    celerity = calculate_celerity(proposition, events)
    shown_events = events[:event_limit] if event_limit is not None else events
    return {
        "id": proposition.pk,
        "house": proposition.house,
        "number_label": proposition.number_label,
        "ementa": proposition.ementa,
        "presented_at": proposition.presented_at,
        "current_status": proposition.current_status,
        "tramitation_url": proposition.tramitation_url,
        "category": annotation.category if annotation else getattr(analysis, "theme_category", None),
        "is_favorable": annotation.is_favorable if annotation else None,
        "assessment_organization": annotation.organization.name if annotation else None,
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


def _queryset():
    return Proposition.objects.select_related("analysis").prefetch_related(
        "events",
        "annotations__organization",
        "authors__parliamentarian",
        "authors__institutional_author",
        "authors__party",
    )


def _cached_activity(proposition_id: int) -> dict | None:
    return cache.get(f"activity:proposition:{proposition_id}")


def _cache_activity(proposition_id: int, activity: dict) -> dict:
    cache.set(f"activity:proposition:{proposition_id}", activity, ACTIVITY_CACHE_TIMEOUT)
    return activity


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
def list_activity(request, limit: int = 5000):
    """All monitored proposals with celerity and their five latest events."""
    limit = min(max(limit, 1), 5000)
    cache_key = f"activity:list:{limit}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    activity = [_serialize(proposition, event_limit=5) for proposition in _queryset().order_by("-presented_at")[:limit]]
    cache.set(cache_key, activity, ACTIVITY_CACHE_TIMEOUT)
    return activity


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


@router.get("/{proposition_id}", response=ActivityPropositionSchema)
def get_activity(request, proposition_id: int):
    return _activity_for_proposition(proposition_id)
