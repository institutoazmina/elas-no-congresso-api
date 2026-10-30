"""Flat read projection for the explorer BFF; never hydrate ORM models or events."""

from collections import defaultdict
from datetime import UTC, datetime, time, timedelta

from django.db.models import Count, Max, Q
from django.utils import timezone

from apps.core.enums import PropositionCategory
from apps.taxonomy.models import PropositionTheme

from .celerity import celerity_from_summary
from .house_transfer import PUBLIC_ORIGIN_Q
from .models import (
    Proposition,
    PropositionAnalysis,
    PropositionAnnotation,
    PropositionAuthor,
    PropositionEvent,
)
from .performance import annotate, stage


def load_explorer_source():
    # Imported at call time because activity owns the shared editorial scope.
    from .activity import PUBLIC_LEGISLATIVE_TYPE_CODES, QUITERIA_ORGANIZATION_NAME

    today = timezone.localdate()
    public = Proposition.objects.filter(
        PUBLIC_ORIGIN_Q, is_approved=True, type_code__in=PUBLIC_LEGISLATIVE_TYPE_CODES
    )
    with stage("source_propositions"):
        rows = list(
            public.order_by("-presented_at", "-pk").values(
                "id",
                "house",
                "type_code",
                "number_label",
                "ementa",
                "presented_at",
                "current_status",
                "tramitation_url",
                "analysis__theme_category",
                "analysis__analysis_status",
                "analysis__classification",
            )
        )
    ids = [row["id"] for row in rows]
    if not ids:
        return []
    transfers = list(
        Proposition.objects.filter(canonical_proposition_id__in=ids)
        .order_by("presented_at", "pk")
        .values("id", "canonical_proposition_id", "house", "current_status", "tramitation_url")
    )
    current_by_origin = {source["canonical_proposition_id"]: source for source in transfers}
    origin_by_source = {source["id"]: source["canonical_proposition_id"] for source in transfers}

    # Django's PostgreSQL connection returns UTC datetimes. Match the existing
    # event_at.date() rule (not a cast in the application's Sao Paulo timezone).
    # No upper bound: the existing celerity rule also counts future events.
    cutoff = datetime.combine(today - timedelta(days=90), time.min, tzinfo=UTC)
    with stage("source_events"):
        events = {
            row["proposition_id"]: row
            for row in (
                PropositionEvent.objects.filter(
                    proposition_id__in=[*ids, *origin_by_source], is_countable=True
                )
                .order_by()
                .values("proposition_id")
                .annotate(
                    last_event_at=Max("event_at"),
                    movements_last_90_days=Count("pk", filter=Q(event_at__gte=cutoff)),
                )
            )
        }
    for source_id, original_id in origin_by_source.items():
        source_event = events.get(source_id)
        if not source_event:
            continue
        original_event = events.setdefault(original_id, {"movements_last_90_days": 0})
        original_event["movements_last_90_days"] += source_event["movements_last_90_days"]
        if source_event["last_event_at"] and (
            not original_event.get("last_event_at")
            or source_event["last_event_at"] > original_event["last_event_at"]
        ):
            original_event["last_event_at"] = source_event["last_event_at"]
    with stage("source_assessments"):
        annotations = {}
        # Stabilize ties with PK, matching the insertion order used by the old
        # prefetch. Human unfavorable > favorable > unrated, before any AI.
        priority = {False: 0, True: 1, None: 2}
        for row in (
            PropositionAnnotation.objects.filter(proposition_id__in=ids)
            .order_by("pk")
            .values(
                "proposition_id",
                "is_favorable",
                "category",
                "comments",
                "relevance",
                "organization__name",
            )
        ):
            previous = annotations.get(row["proposition_id"])
            if (
                previous is None
                or priority[row["is_favorable"]] < priority[previous["is_favorable"]]
            ):
                annotations[row["proposition_id"]] = row
    with stage("source_authors"):
        authors = defaultdict(list)
        for row in (
            PropositionAuthor.objects.filter(proposition_id__in=ids)
            .order_by("pk")
            .values(
                "proposition_id",
                "parliamentarian_id",
                "parliamentarian__social_name",
                "parliamentarian__full_name",
                "parliamentarian__photo_url",
                "parliamentarian__gender",
                "parliamentarian__religion",
                "institutional_author__name",
                "party__acronym",
                "state_at_authorship",
            )
        ):
            person = row["parliamentarian_id"] is not None
            authors[row["proposition_id"]].append(
                {
                    "id": row["parliamentarian_id"],
                    "name": (
                        row["parliamentarian__social_name"] or row["parliamentarian__full_name"]
                    )
                    if person
                    else row["institutional_author__name"],
                    "photo_url": row["parliamentarian__photo_url"],
                    "gender": row["parliamentarian__gender"],
                    "religion": row["parliamentarian__religion"],
                    "party": row["party__acronym"],
                    "state": row["state_at_authorship"],
                    "role": None,
                }
            )
    # Preserve the existing HTTP contract without loading Theme model objects.
    with stage("source_themes"):
        themes = defaultdict(list)
        for proposition_id, name in (
            PropositionTheme.objects.filter(proposition_id__in=ids)
            .order_by("pk")
            .values_list("proposition_id", "theme__name")
        ):
            themes[proposition_id].append(name)

    labels = dict(PropositionCategory.choices)
    items = []
    with stage("source_serialize"):
        for row in rows:
            pk = row["id"]
            current = current_by_origin.get(pk, row)
            annotation = annotations.get(pk)
            category = annotation["category"] if annotation else row["analysis__theme_category"]
            classified = row[
                "analysis__analysis_status"
            ] == PropositionAnalysis.Status.SUCCEEDED and row["analysis__classification"] in (0, 1)
            event = events.get(pk, {})
            celerity = celerity_from_summary(
                row["presented_at"],
                event.get("last_event_at"),
                event.get("movements_last_90_days", 0),
                today=today,
            )
            items.append(
                {
                    **{
                        name: row[name]
                        for name in (
                            "id",
                            "house",
                            "type_code",
                            "number_label",
                            "ementa",
                            "presented_at",
                            "current_status",
                            "tramitation_url",
                        )
                    },
                    "current_house": current["house"],
                    "current_status": current["current_status"],
                    "tramitation_url": current["tramitation_url"],
                    "category": category,
                    "category_label": labels.get(category, category) if category else None,
                    "is_favorable": annotation["is_favorable"]
                    if annotation
                    else row["analysis__classification"] == 0
                    if classified
                    else None,
                    "assessment_organization": annotation["organization__name"]
                    if annotation
                    else QUITERIA_ORGANIZATION_NAME
                    if classified
                    else None,
                    "assessment_comments": annotation["comments"] if annotation else None,
                    "relevance": annotation["relevance"] if annotation else None,
                    "authors": authors[pk],
                    "themes": themes[pk],
                    "events": [],
                    "celerity": {
                        "label": celerity.label,
                        "days_without_movement": celerity.days_without_movement,
                        "movements_last_90_days": celerity.movements_last_90_days,
                        "last_event_at": celerity.last_event_at,
                    },
                }
            )
    annotate(
        source_count=len(items),
        event_aggregate_count=len(events),
        authorship_count=sum(map(len, authors.values())),
    )
    return items
