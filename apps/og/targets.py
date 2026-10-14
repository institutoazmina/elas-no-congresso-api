"""Quem recebe imagem de compartilhamento e o que vai desenhado nela.

Espelha as regras do site (``src/lib/author-paths.ts`` e ``author-page.ts``):
autoras das proposições do ``/activity?limit=5000``, slug do nome com a
primeira autora vencendo colisões, e totais deduplicados por casa e número.
"""

import json
import re
import unicodedata
from dataclasses import dataclass
from hashlib import sha256

from apps.legislatures.models import Parliamentarian
from apps.propositions.activity import PUBLIC_LEGISLATIVE_TYPE_CODES, public_is_favorable
from apps.propositions.models import Proposition, PropositionAuthor

# Incrementar força a renderização de todas as imagens.
RENDERER_VERSION = 1
# Mesmo limite que o site usa ao buscar a atividade no build.
SITE_ACTIVITY_LIMIT = 5000


@dataclass(frozen=True)
class OgTarget:
    parliamentarian_id: int
    slug: str
    name: str
    affiliation: str
    favorable: int
    unfavorable: int
    photo_url: str | None

    @property
    def s3_key(self) -> str:
        return og_key(self.slug)

    @property
    def fingerprint(self) -> str:
        payload = [
            RENDERER_VERSION,
            self.slug,
            self.name,
            self.affiliation,
            self.favorable,
            self.unfavorable,
            self.photo_url,
        ]
        return sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


def og_key(slug: str) -> str:
    return f"atividade-legislativa/autoria/{slug}/og.png"


def author_slug(value) -> str | None:
    """Porta de ``authorSlug`` do site."""
    text = unicodedata.normalize("NFD", str(value or ""))
    text = re.sub(r"[\u0300-\u036f]", "", text).lower()
    text = re.sub(r"[^a-z0-9]+", "-", text).strip("-")
    return text or None


def normalize_photo_url(value) -> str | None:
    """Porta de ``normalizePhotoUrl`` do site."""
    url = str(value or "").strip()
    if not url or url == "Indisponível":
        return None
    return re.sub(r"^http:", "https:", url)


def _display_name(social_name, full_name) -> str:
    return social_name or full_name or ""


def _window_ids() -> list[int]:
    return list(
        Proposition.objects.filter(is_approved=True, type_code__in=PUBLIC_LEGISLATIVE_TYPE_CODES)
        .order_by("-presented_at")
        .values_list("pk", flat=True)[:SITE_ACTIVITY_LIMIT]
    )


def _slug_owners(window: list[int]) -> tuple[dict[int, str], dict[int, str]]:
    """Slug de cada autora dona do slug e a UF da primeira autoria vista."""
    rows = (
        PropositionAuthor.objects.filter(proposition_id__in=window, parliamentarian__isnull=False)
        .order_by("pk")
        .values_list(
            "proposition_id",
            "parliamentarian_id",
            "parliamentarian__social_name",
            "parliamentarian__full_name",
            "state_at_authorship",
        )
    )
    by_proposition: dict[int, list[tuple]] = {}
    for proposition_id, *author in rows:
        by_proposition.setdefault(proposition_id, []).append(author)

    seen: set[int] = set()
    owners: dict[str, int] = {}
    states: dict[int, str] = {}
    for proposition_id in window:
        for parliamentarian_id, social_name, full_name, state in by_proposition.get(
            proposition_id, []
        ):
            if parliamentarian_id in seen:
                continue
            seen.add(parliamentarian_id)
            states[parliamentarian_id] = state or ""
            slug = author_slug(_display_name(social_name, full_name))
            if slug and slug not in owners:
                owners[slug] = parliamentarian_id
    return {pid: slug for slug, pid in owners.items()}, states


def _counts(window: list[int], parliamentarian_ids: set[int]) -> dict[int, tuple[int, int]]:
    order = {pk: index for index, pk in enumerate(window)}
    propositions = (
        Proposition.objects.filter(
            pk__in=window, authors__parliamentarian_id__in=parliamentarian_ids
        )
        .distinct()
        .select_related("analysis")
        .prefetch_related("annotations", "authors")
    )
    # O site guarda a última proposição vista por ``casa:número``.
    assessments: dict[int, dict[tuple[str, str], bool | None]] = {}
    for proposition in sorted(propositions, key=lambda item: order[item.pk]):
        is_favorable = public_is_favorable(proposition)
        key = (proposition.house, proposition.number_label)
        for author in proposition.authors.all():
            if author.parliamentarian_id in parliamentarian_ids:
                assessments.setdefault(author.parliamentarian_id, {})[key] = is_favorable
    return {
        pid: (
            sum(1 for value in values.values() if value is True),
            sum(1 for value in values.values() if value is False),
        )
        for pid, values in assessments.items()
    }


def _affiliation(parliamentarian: Parliamentarian, fallback_state: str) -> str:
    terms = list(parliamentarian.terms.all())
    term = next((item for item in terms if item.end_date is None), terms[0] if terms else None)
    if term is None:
        party, state = "Indisponível", fallback_state
    else:
        party = (term.party.acronym or "").strip() or "Indisponível"
        state = term.state or fallback_state
    return "/".join(part for part in (party, state) if part)


def build_targets(parliamentarian_ids: set[int] | None = None) -> dict[int, OgTarget]:
    """Alvos atuais; quem não aparece no resultado não deve ter imagem."""
    window = _window_ids()
    slugs, states = _slug_owners(window)
    ids = set(slugs) if parliamentarian_ids is None else set(slugs) & set(parliamentarian_ids)
    if not ids:
        return {}
    counts = _counts(window, ids)
    people = Parliamentarian.objects.filter(pk__in=ids).prefetch_related("terms__party")
    return {
        person.pk: OgTarget(
            parliamentarian_id=person.pk,
            slug=slugs[person.pk],
            name=_display_name(person.social_name, person.full_name),
            affiliation=_affiliation(person, states.get(person.pk, "")),
            favorable=counts.get(person.pk, (0, 0))[0],
            unfavorable=counts.get(person.pk, (0, 0))[1],
            photo_url=normalize_photo_url(person.photo_url),
        )
        for person in people
    }
