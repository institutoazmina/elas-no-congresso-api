"""Public read model for legislative monitoring and celerity."""

from datetime import date, datetime

from ninja import Router, Schema

from .celerity import calculate_celerity
from .models import Proposition

router = Router()


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
                "title": event.title,
                "description": event.description,
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


@router.get("", response=list[ActivityPropositionSchema])
def list_activity(request, limit: int = 5000):
    """All monitored proposals with celerity and their five latest events."""
    limit = min(max(limit, 1), 5000)
    return [_serialize(proposition, event_limit=5) for proposition in _queryset().order_by("-presented_at")[:limit]]


@router.get("/{proposition_id}", response=ActivityPropositionSchema)
def get_activity(request, proposition_id: int):
    from django.shortcuts import get_object_or_404

    return _serialize(get_object_or_404(_queryset(), pk=proposition_id), event_limit=None)
