"""Transactional persistence for normalized parliamentarian profiles."""

from collections.abc import Mapping
from datetime import date, timedelta

from django.db import transaction
from django.utils import timezone

from apps.core.enums import House
from apps.legislatures.models import (
    Parliamentarian,
    ParliamentarianProfileSource,
    ParliamentarianTerm,
)

PROFILE_FIELDS = (
    "full_name",
    "social_name",
    "photo_url",
    "gender",
    "birth_date",
    "race",
    "education",
    "birthplace",
    "profession",
    "religion",
    "bio",
)

MANUAL_SOURCE = "manual"
OFFICIAL_SOURCE = "official"
TSE_SOURCE = "tse"
LEGACY_SOURCE = "legacy"
RECENT_TERM_WINDOW = timedelta(days=4 * 365)


class ProfileIdentityError(ValueError):
    """The source key cannot be assigned to exactly one parliamentarian."""


class ProfileAmbiguityError(ProfileIdentityError):
    """Matching terms belong to more than one parliamentarian."""


class ProfileIdentityConflictError(ProfileIdentityError):
    """A stable source identity is already assigned to another person."""


ProfileIdentityConflict = ProfileIdentityConflictError


class ProfileConflictError(ProfileIdentityConflictError):
    """Descriptive name for source identity conflicts."""


def _canonical_source(source: object) -> str:
    if source is None:
        raise ProfileIdentityError("source is required")
    source = str(source).strip().casefold()
    if not source:
        raise ProfileIdentityError("source is required")
    return source


def _canonical_house(house: object) -> str:
    try:
        return House(house).value
    except (TypeError, ValueError):
        raise ProfileIdentityError(f"unknown house: {house!r}") from None


def _external_id(value: object) -> int:
    if value is None or isinstance(value, bool):
        raise ProfileIdentityError("a numeric source key is required")
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        raise ProfileIdentityError("source_key must identify an external numeric id") from None
    if parsed < 0:
        raise ProfileIdentityError("source_key must identify a non-negative external id")
    return parsed


def _canonical_source_key(source_key: object) -> str:
    if source_key is None:
        raise ProfileIdentityError("source_key is required")
    source_key = str(source_key).strip()
    if not source_key:
        raise ProfileIdentityError("source_key is required")
    return source_key


def _json_value(value: object) -> object:
    if isinstance(value, date):
        return value.isoformat()
    return value


def _normalized_profile_values(
    values: Mapping[str, object], *, external_id: int
) -> dict[str, object]:
    if not isinstance(values, Mapping):
        raise ProfileIdentityError("profile_values must be a mapping")

    supplied_external_id = values.get("external_id")
    if supplied_external_id is not None and _external_id(supplied_external_id) != external_id:
        raise ProfileIdentityConflictError("profile external_id conflicts with source_key")

    # Filtering is intentional: raw fields and identity/provenance keys cannot
    # escape into the source snapshot or the public detail schema.
    return {
        field: _json_value(values[field])
        for field in PROFILE_FIELDS
        if field in values
    }


def _source_rank(source: str) -> int:
    normalized = source.casefold()
    if normalized == MANUAL_SOURCE or normalized.startswith("manual:"):
        return 4
    if (
        normalized == OFFICIAL_SOURCE
        or normalized.startswith("official:")
        or normalized in {"camara", "senado"}
    ):
        return 3
    if normalized == TSE_SOURCE or normalized.startswith("tse:"):
        return 2
    if normalized == LEGACY_SOURCE or normalized.startswith("legacy:"):
        return 1
    # Keep unknown adapters between official and legacy sources until their
    # precedence is explicitly defined.
    return 2


def _requires_official_activity_gate(source: str) -> bool:
    normalized = source.casefold()
    return (
        normalized == OFFICIAL_SOURCE
        or normalized.startswith("official:")
        or normalized in {"camara", "senado"}
    )


def _official_is_active_or_recent(profile, house: str) -> bool:
    metadata = profile.metadata if isinstance(profile.metadata, Mapping) else {}
    term_source_key = metadata.get("term_external_id") or profile.source_key
    try:
        external_id = _external_id(term_source_key)
    except ProfileIdentityError:
        return False

    terms = list(
        ParliamentarianTerm.objects.filter(
            parliamentarian_id=profile.parliamentarian_id,
            house=house,
            external_id=external_id,
        )
    )
    if not terms or len({term.parliamentarian_id for term in terms}) != 1:
        return False
    cutoff = timezone.localdate() - RECENT_TERM_WINDOW
    return any(term.end_date is None or term.end_date >= cutoff for term in terms)


def _candidate_profiles(
    profiles: list[ParliamentarianProfileSource], *, house: str
) -> list[tuple[int, object, int, ParliamentarianProfileSource]]:
    candidates = []
    for profile in profiles:
        rank = _source_rank(profile.source)
        if _requires_official_activity_gate(profile.source) and not _official_is_active_or_recent(
            profile, house
        ):
            continue
        candidates.append((rank, profile.last_seen_at, profile.pk, profile))
    candidates.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return candidates


def _resolved_values(
    profiles: list[ParliamentarianProfileSource], *, house: str
) -> dict[str, object]:
    resolved: dict[str, object] = {}
    for _, _, _, profile in _candidate_profiles(profiles, house=house):
        for field, value in profile.profile_values.items():
            # None is retained in the snapshot, but cannot erase a projection
            # or shadow a lower-priority non-null value.
            if field in PROFILE_FIELDS and value is not None and field not in resolved:
                resolved[field] = value
    return resolved


def _direct_value(value: object, field: str) -> object:
    if value is None or field != "birth_date":
        return value
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise ProfileIdentityError(f"invalid birth_date for profile field: {value!r}") from None


def _project_direct_profile(
    parliamentarian: Parliamentarian,
    resolved: Mapping[str, object],
) -> None:
    changed_fields = []
    for field in PROFILE_FIELDS:
        if field not in resolved or resolved[field] is None:
            continue
        value = _direct_value(resolved[field], field)
        if getattr(parliamentarian, field) != value:
            setattr(parliamentarian, field, value)
            changed_fields.append(field)

    if changed_fields:
        parliamentarian.save(update_fields=[*changed_fields, "updated_at"])


@transaction.atomic
def upsert_source_profile(
    *,
    source: str,
    source_key: object | None = None,
    house: str | House,
    profile_values: Mapping[str, object] | None = None,
    source_url: str | None = None,
    external_id: object | None = None,
    profile: Mapping[str, object] | None = None,
    metadata: Mapping[str, object] | None = None,
) -> ParliamentarianProfileSource:
    """Persist one source snapshot and its direct profile projection.

    ``source_key`` is the external parliamentarian id for this tracer. The
    optional ``external_id``/``profile`` spellings make it convenient to pass
    normalized mapper output while still requiring the same term lookup.
    """

    source = _canonical_source(source)
    values = profile_values if profile_values is not None else profile
    if values is None:
        values = {}
    if source_key is None and external_id is not None:
        source_key = external_id
    if source_key is None and isinstance(values, Mapping):
        source_key = values.get("external_id")
    source_key = _canonical_source_key(source_key)
    source_external_id = _external_id(external_id if external_id is not None else source_key)
    if metadata is not None and not isinstance(metadata, Mapping):
        raise ProfileIdentityError("metadata must be a mapping")
    normalized_metadata = dict(metadata or {})
    if external_id is not None and _external_id(external_id) != source_external_id:
        raise ProfileIdentityConflictError("external_id conflicts with source_key")
    house = _canonical_house(house)
    normalized_values = _normalized_profile_values(values, external_id=source_external_id)

    terms = list(
        ParliamentarianTerm.objects.select_for_update()
        .filter(house=house, external_id=source_external_id)
        .order_by("pk")
    )
    if not terms:
        raise ProfileIdentityError(
            f"no ParliamentarianTerm matches house={house!r}, external_id={source_external_id}"
        )
    if len({term.parliamentarian_id for term in terms}) != 1:
        raise ProfileAmbiguityError(
            "matching ParliamentarianTerms belong to multiple parliamentarians "
            f"for house={house!r}, external_id={source_external_id}"
        )

    term = terms[0]
    existing = (
        ParliamentarianProfileSource.objects.select_for_update()
        .filter(source=source, source_key=source_key)
        .first()
    )
    if existing is not None and existing.parliamentarian_id != term.parliamentarian_id:
        raise ProfileConflictError(
            f"source={source!r}, source_key={source_key!r} is assigned to another parliamentarian"
        )

    parliamentarian = Parliamentarian.objects.select_for_update().get(pk=term.parliamentarian_id)
    now = timezone.now()
    if existing is None:
        snapshot = ParliamentarianProfileSource.objects.create(
            parliamentarian=parliamentarian,
            source=source,
            source_key=source_key,
            profile_values=normalized_values,
            metadata=normalized_metadata,
            source_url=source_url,
            first_seen_at=now,
            last_seen_at=now,
        )
    else:
        snapshot = existing
        previous_values = snapshot.profile_values if isinstance(snapshot.profile_values, Mapping) else {}
        snapshot.profile_values = {**previous_values, **normalized_values}
        if source_url is not None:
            snapshot.source_url = source_url
        if metadata is not None:
            snapshot.metadata = normalized_metadata
        snapshot.last_seen_at = now
        update_fields = ["profile_values", "source_url", "last_seen_at"]
        if metadata is not None:
            update_fields.append("metadata")
        snapshot.save(update_fields=update_fields)

    profiles = list(
        ParliamentarianProfileSource.objects.filter(parliamentarian_id=parliamentarian.pk)
    )
    _project_direct_profile(parliamentarian, _resolved_values(profiles, house=house))
    return snapshot


def upsert_parliamentarian_profile(**kwargs):
    """Descriptive alias for callers that do not use the table's name."""

    return upsert_source_profile(**kwargs)
