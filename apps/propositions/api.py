

from ninja import Router
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
    q: str | None = None,
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
        qs = qs.filter(
            Q(number_label__icontains=q) | Q(ementa__icontains=q) | Q(keywords__icontains=q)
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
