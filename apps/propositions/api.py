

import unicodedata
from typing import Annotated

from ninja import Query, Router
from ninja.pagination import LimitOffsetPagination, paginate

from .models import Proposition
from .schemas import PropositionDetailSchema, PropositionSchema

router = Router()


@router.get("", response=list[PropositionSchema])
@paginate(LimitOffsetPagination)
def list_propositions(
    request,
    house: str | None = None,
    year: int | None = None,
    theme: str | None = None,
    active: bool | None = None,
    q: Annotated[
        str | None,
        Query(  # type: ignore[operator]
            description=(
                "Busca parcial por ementa, número da proposição ou nome completo ou social "
                "de autores e coautores. A busca por autor ignora maiúsculas, minúsculas "
                "e acentos."
            )
        ),
    ] = None,
):
    qs = Proposition.objects.all()
    if house:
        qs = qs.filter(house=house)
    if year:
        qs = qs.filter(year=year)
    if theme:
        qs = qs.filter(proposition_themes__theme__slug=theme)
    if active is not None:
        qs = qs.filter(is_active=active)
    if q:
        from django.db.models import Q

        normalized_q = "".join(
            character
            for character in unicodedata.normalize("NFKD", q)
            if not unicodedata.combining(character)
        )
        qs = qs.filter(
            Q(number_label__icontains=q)
            | Q(ementa__icontains=q)
            | Q(keywords__icontains=q)
            | Q(authors__parliamentarian__full_name__unaccent__icontains=normalized_q)
            | Q(authors__parliamentarian__social_name__unaccent__icontains=normalized_q)
        ).order_by("-presented_at")
    else:
        qs = qs.order_by("-presented_at")
    return qs.distinct()


@router.get("/{proposition_id}", response=PropositionDetailSchema)
def get_proposition(request, proposition_id: int):
    from django.shortcuts import get_object_or_404
    return get_object_or_404(
        Proposition.objects.prefetch_related(
            "authors__parliamentarian",
            "authors__institutional_author",
            "rapporteurs__parliamentarian",
            "proposition_themes__theme",
        ).select_related("analysis"),
        pk=proposition_id,
    )
