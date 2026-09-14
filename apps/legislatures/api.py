
from django.db.models import Count, Exists, OuterRef, Q
from django.utils import timezone
from ninja import Router
from ninja.pagination import LimitOffsetPagination, paginate

from .models import Legislature, Parliamentarian, ParliamentarianTerm, Party
from .schemas import (
    LegislatureSchema,
    ParliamentarianDetailSchema,
    ParliamentarianSchema,
    PartySchema,
)

router = Router()


def _parliamentarians_with_proposition_counts():
    return Parliamentarian.objects.annotate(
        favorable_propositions_count=Count(
            "authored_propositions__proposition",
            distinct=True,
            filter=Q(authored_propositions__proposition__annotations__is_favorable=True),
        ),
        unfavorable_propositions_count=Count(
            "authored_propositions__proposition",
            distinct=True,
            filter=Q(authored_propositions__proposition__annotations__is_favorable=False),
        ),
    )


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
    qs = _parliamentarians_with_proposition_counts().prefetch_related("terms")
    if current:
        today = timezone.localdate()
        current_term = ParliamentarianTerm.objects.filter(
            parliamentarian_id=OuterRef("pk"),
            start_date__lte=today,
        ).filter(Q(end_date__isnull=True) | Q(end_date__gte=today))
        if house:
            current_term = current_term.filter(house=house)
        if state:
            current_term = current_term.filter(state__iexact=state)
        if party:
            current_term = current_term.filter(party__acronym__iexact=party)
        qs = qs.filter(Exists(current_term))
    elif house or state or party:
        term_filter = {}
        if house:
            term_filter["terms__house"] = house
        if state:
            term_filter["terms__state__iexact"] = state
        if party:
            term_filter["terms__party__acronym__iexact"] = party
        qs = qs.filter(**term_filter).distinct()
    if gender:
        qs = qs.filter(gender=gender)
    return qs.order_by("full_name")


@router.get("/parliamentarians/{parliamentarian_id}", response=ParliamentarianDetailSchema)
def get_parliamentarian(request, parliamentarian_id: int):
    from django.shortcuts import get_object_or_404
    return get_object_or_404(
        _parliamentarians_with_proposition_counts().prefetch_related("terms", "contacts"),
        pk=parliamentarian_id,
    )
