
from ninja import Router
from ninja.pagination import LimitOffsetPagination, paginate

from .models import Legislature, Parliamentarian, Party
from .schemas import (
    LegislatureSchema,
    ParliamentarianDetailSchema,
    ParliamentarianSchema,
    PartySchema,
)

router = Router()


@router.get("/legislatures", response=list[LegislatureSchema])
def list_legislatures(request):
    return Legislature.objects.all().order_by("-number")


@router.get("/parties", response=list[PartySchema])
@paginate(LimitOffsetPagination)
def list_parties(request):
    return Party.objects.all().order_by("acronym")


@router.get("/parliamentarians", response=list[ParliamentarianSchema])
@paginate(LimitOffsetPagination)
def list_parliamentarians(
    request,
    house: str | None = None,
    state: str | None = None,
    party: str | None = None,
    gender: str | None = None,
    current: bool | None = None,
):
    qs = Parliamentarian.objects.all()
    if house or state or party or current is not None:
        term_filter = {}
        if house:
            term_filter["terms__house"] = house
        if state:
            term_filter["terms__state__iexact"] = state
        if party:
            term_filter["terms__party__acronym__iexact"] = party
        if current:
            term_filter["terms__end_date__isnull"] = True
        qs = qs.filter(**term_filter).distinct()
    if gender:
        qs = qs.filter(gender=gender)
    return qs.order_by("full_name")


@router.get("/parliamentarians/{parliamentarian_id}", response=ParliamentarianDetailSchema)
def get_parliamentarian(request, parliamentarian_id: int):
    from django.shortcuts import get_object_or_404
    return get_object_or_404(
        Parliamentarian.objects.prefetch_related("terms", "contacts"),
        pk=parliamentarian_id,
    )
