"""Endpoints agregados (BFF) — um por gráfico da home do front.

Regras de contagem (decididas com o produto, valem para todos os cortes):

- 1 "desfavorável" = 1 proposição DISTINTA com ao menos uma anotação
  ``is_favorable=False``. Avaliadoras divergentes sobre a mesma proposição não
  a contam duas vezes, e na dúvida ela entra como desfavorável.
- Cortes por partido/estado/gênero atribuem a proposição a TODOS os seus
  coautores. A soma dos grupos é portanto maior que o total geral — é ranking,
  não partição.
- Nomes dos campos em inglês (``favorable``/``unfavorable``), como o resto da API.
"""

from typing import Literal

from django.db.models import Count, F, Q
from django.utils import timezone
from ninja import Field, Router, Schema

from apps.core.enums import Gender, PropositionCategory
from apps.legislatures.models import Legislature

from .models import Proposition, PropositionAnnotation, PropositionAuthor

router = Router()

FAVORABLE = Q(annotations__is_favorable=True)
UNFAVORABLE = Q(annotations__is_favorable=False)
# Mesmos filtros a partir de PropositionAuthor (um join a mais).
BY_AUTHOR_FAVORABLE = Q(proposition__annotations__is_favorable=True)
BY_AUTHOR_UNFAVORABLE = Q(proposition__annotations__is_favorable=False)

Stance = Literal["unfavorable", "favorable"]


# ── schemas ───────────────────────────────────────────────────────────────────

class LegislatureCountSchema(Schema):
    number: int
    from_year: int = Field(alias="from")
    to_year: int = Field(alias="to")
    label: str
    unfavorable: int


class LegislatureStatsSchema(Schema):
    legislatures: list[LegislatureCountSchema]


class CategoryCountSchema(Schema):
    value: str  # slug do enum, para o front filtrar
    label: str
    unfavorable: int


class CategoryStatsSchema(Schema):
    categories: list[CategoryCountSchema]


class StanceRatioSchema(Schema):
    favorable: float
    unfavorable: float


class GenderStatsSchema(Schema):
    women: StanceRatioSchema
    men: StanceRatioSchema


class GroupCountSchema(Schema):
    label: str
    favorable: int
    unfavorable: int


class PartyStatsSchema(Schema):
    parties: list[GroupCountSchema]


class StateStatsSchema(Schema):
    states: list[GroupCountSchema]


# ── endpoints ─────────────────────────────────────────────────────────────────

@router.get("/legislatures", response=LegislatureStatsSchema, by_alias=True)
def unfavorable_by_legislature(request, last: int = 2):
    """Proposições desfavoráveis por legislatura, da mais antiga para a mais nova.

    Não há FK proposição→legislatura: o vínculo é a data de apresentação dentro
    da janela da legislatura. São poucas legislaturas, então vira um COUNT
    filtrado por legislatura numa única query.

    A tabela tem as 60 legislaturas desde 1826, mas só há dados de 2019 em
    diante (planilha das avaliadoras). ``last`` recorta as N mais recentes já
    iniciadas — nunca as futuras, que seriam sempre zero. ``last=0`` traz todas.
    """
    query = Legislature.objects.filter(start_date__lte=timezone.localdate())
    legislatures = sorted(query.order_by("-number")[:last] if last else query, key=lambda leg: leg.number)
    if not legislatures:
        return {"legislatures": []}

    counts = Proposition.objects.aggregate(
        **{
            f"leg_{leg.number}": Count(
                "id",
                distinct=True,
                filter=UNFAVORABLE & Q(presented_at__range=(leg.start_date, leg.end_date)),
            )
            for leg in legislatures
        }
    )
    return {
        "legislatures": [
            {
                "number": leg.number,
                "from": leg.start_date.year,
                "to": leg.end_date.year,
                "label": str(leg),
                "unfavorable": counts[f"leg_{leg.number}"],
            }
            for leg in legislatures
        ]
    }


@router.get("/categories", response=CategoryStatsSchema)
def unfavorable_by_category(request):
    """Proposições desfavoráveis por categoria (taxonomia Categorias 2026)."""
    labels = dict(PropositionCategory.choices)
    rows = (
        PropositionAnnotation.objects.filter(is_favorable=False)
        .values("category")
        .annotate(unfavorable=Count("proposition", distinct=True))
        .order_by("-unfavorable")
    )
    return {
        "categories": [
            {
                "value": row["category"],
                "label": labels.get(row["category"], row["category"]),
                "unfavorable": row["unfavorable"],
            }
            for row in rows
        ]
    }


@router.get("/genders", response=GenderStatsSchema)
def stance_by_gender(request):
    """Proporção favorável/desfavorável DENTRO de cada gênero (soma 1.0 cada).

    Lê-se: "das proposições autoradas por mulheres, X% são desfavoráveis".
    Autoria não-binária/não informada fica fora deste recorte.
    """
    rows = (
        Proposition.objects.filter(
            authors__parliamentarian__gender__in=[Gender.F, Gender.M]
        )
        .values(gender=F("authors__parliamentarian__gender"))
        .annotate(
            favorable=Count("id", distinct=True, filter=FAVORABLE),
            unfavorable=Count("id", distinct=True, filter=UNFAVORABLE),
        )
    )
    by_gender = {row["gender"]: row for row in rows}

    def ratio(gender: str) -> dict[str, float]:
        row = by_gender.get(gender, {"favorable": 0, "unfavorable": 0})
        total = row["favorable"] + row["unfavorable"]
        if not total:
            return {"favorable": 0.0, "unfavorable": 0.0}
        return {
            "favorable": round(row["favorable"] / total, 4),
            "unfavorable": round(row["unfavorable"] / total, 4),
        }

    return {"women": ratio(Gender.F), "men": ratio(Gender.M)}


def _by_author_group(field: str, stance: Stance, limit: int) -> list[dict]:
    """Ranking de grupos de autoria (partido, estado) por favoráveis/desfavoráveis."""
    return list(
        PropositionAuthor.objects.exclude(**{f"{field}__isnull": True})
        .exclude(**{field: ""})
        .values(label=F(field))
        .annotate(
            favorable=Count("proposition", distinct=True, filter=BY_AUTHOR_FAVORABLE),
            unfavorable=Count("proposition", distinct=True, filter=BY_AUTHOR_UNFAVORABLE),
        )
        .order_by(f"-{stance}", "label")[:limit]
    )


@router.get("/parties", response=PartyStatsSchema)
def stance_by_party(request, stance: Stance = "unfavorable", limit: int = 5):
    """Top N partidos, ranqueados pela métrica escolhida em ``stance``."""
    return {"parties": _by_author_group("party__acronym", stance, limit)}


@router.get("/states", response=StateStatsSchema)
def stance_by_state(request, stance: Stance = "unfavorable", limit: int = 5):
    """Top N estados (UF do parlamentar na autoria), ranqueados por ``stance``."""
    return {"states": _by_author_group("state_at_authorship", stance, limit)}
