

import unicodedata
from typing import Annotated, Literal

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
            max_length=200,
            description=(
                "Busca parcial por ementa, número da proposição ou nome completo ou social "
                "de autores e coautores. A busca por autor ignora maiúsculas, minúsculas "
                "e acentos."
            )
        ),
    ] = None,
    sort: Annotated[
        Literal["newest", "oldest"],
        Query(  # type: ignore[operator]
            description=(
                "Ordena por presented_at: newest do mais recente para o mais antigo; "
                "oldest do mais antigo para o mais recente."
            )
        ),
    ] = "newest",
):
    # A API pública nunca expõe itens ainda não curados, nem documentos fora
    # do escopo editorial. O gerenciador continua vendo ambos para revisão.
    from .activity import PUBLIC_LEGISLATIVE_TYPE_CODES

    qs = Proposition.objects.filter(is_approved=True, type_code__in=PUBLIC_LEGISLATIVE_TYPE_CODES)
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
        )
    ordering = ("-presented_at", "-id") if sort == "newest" else ("presented_at", "id")
    return qs.order_by(*ordering).distinct()


@router.get("/{proposition_id}", response=PropositionDetailSchema)
def get_proposition(request, proposition_id: int):
    from django.shortcuts import get_object_or_404

    from .activity import PUBLIC_LEGISLATIVE_TYPE_CODES

    return get_object_or_404(
        Proposition.objects.filter(
            is_approved=True, type_code__in=PUBLIC_LEGISLATIVE_TYPE_CODES
        ).prefetch_related(
            "authors__parliamentarian",
            "authors__institutional_author",
            "rapporteurs__parliamentarian",
            "proposition_themes__theme",
        ).select_related("analysis"),
        pk=proposition_id,
    )
