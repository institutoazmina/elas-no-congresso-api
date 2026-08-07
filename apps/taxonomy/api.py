
from ninja import Router

from apps.core.enums import PropositionCategory

from .models import AnalyticalTag, Theme
from .schemas import AnalyticalTagSchema, CategorySchema, ThemeSchema

router = Router()


@router.get("/categories", response=list[CategorySchema])
def list_categories(request):
    """Categorias 2026: taxonomia editorial fechada das anotações humanas.

    É o corte que o site oferece para escolher (10 itens), diferente de
    `/themes`, que são as palavras-chave granulares vindas do raspador.
    """
    return [{"value": value, "label": label} for value, label in PropositionCategory.choices]


@router.get("/themes", response=list[ThemeSchema])
def list_themes(request):
    return Theme.objects.all().order_by("name")


@router.get("/tags", response=list[AnalyticalTagSchema])
def list_tags(request):
    return AnalyticalTag.objects.all().order_by("name")
