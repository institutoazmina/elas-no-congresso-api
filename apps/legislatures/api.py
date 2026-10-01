
from typing import Literal

from django.db.models import Count, Exists, ExpressionWrapper, F, FloatField, OuterRef, Q
from django.db.models.functions import Cast
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
    # Os totais que chegam ao site devem obedecer à mesma curadoria da API de
    # atividade: somente proposições aprovadas e tipos legislativos públicos.
    # Quando não há avaliação humana, a classificação concluída pela QuitérIA
    # passa a compor os totais de favorabilidade.
    from apps.propositions.activity import PUBLIC_LEGISLATIVE_TYPE_CODES
    from apps.propositions.models import PropositionAnalysis

    public_proposition = Q(
        authored_propositions__proposition__is_approved=True,
        authored_propositions__proposition__type_code__in=PUBLIC_LEGISLATIVE_TYPE_CODES,
    )
    automatic_favorable = Q(
        authored_propositions__proposition__annotations__isnull=True,
        authored_propositions__proposition__analysis__analysis_status=PropositionAnalysis.Status.SUCCEEDED,
        authored_propositions__proposition__analysis__classification=0,
    )
    automatic_unfavorable = Q(
        authored_propositions__proposition__annotations__isnull=True,
        authored_propositions__proposition__analysis__analysis_status=PropositionAnalysis.Status.SUCCEEDED,
        authored_propositions__proposition__analysis__classification=1,
    )
    return Parliamentarian.objects.annotate(
        public_propositions_count=Count(
            "authored_propositions__proposition",
            distinct=True,
            filter=public_proposition,
        ),
        favorable_propositions_count=Count(
            "authored_propositions__proposition",
            distinct=True,
            filter=public_proposition
            & (
                Q(authored_propositions__proposition__annotations__is_favorable=True)
                | automatic_favorable
            ),
        ),
        unfavorable_propositions_count=Count(
            "authored_propositions__proposition",
            distinct=True,
            filter=public_proposition
            & (
                Q(authored_propositions__proposition__annotations__is_favorable=False)
                | automatic_unfavorable
            ),
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
    rank: Literal["unfavorable", "unfavorable_rate"] | None = None,
    min_propositions: int = 0,
    min_unfavorable_rate: float = 0,
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
    if min_propositions > 0:
        qs = qs.filter(public_propositions_count__gte=min_propositions)
    if rank == "unfavorable_rate":
        qs = qs.annotate(
            unfavorable_rate=ExpressionWrapper(
                Cast(F("unfavorable_propositions_count"), FloatField())
                / Cast(F("public_propositions_count"), FloatField()),
                output_field=FloatField(),
            )
        ).filter(unfavorable_rate__gte=min_unfavorable_rate)
        return qs.order_by(
            "-unfavorable_rate", "-unfavorable_propositions_count", "-public_propositions_count", "full_name"
        )
    if rank == "unfavorable":
        return qs.order_by(
            "-unfavorable_propositions_count", "-public_propositions_count", "full_name"
        )
    return qs.order_by("full_name")


@router.get("/parliamentarians/{parliamentarian_id}", response=ParliamentarianDetailSchema)
def get_parliamentarian(request, parliamentarian_id: int):
    from django.shortcuts import get_object_or_404
    return get_object_or_404(
        _parliamentarians_with_proposition_counts().prefetch_related("terms", "contacts"),
        pk=parliamentarian_id,
    )
