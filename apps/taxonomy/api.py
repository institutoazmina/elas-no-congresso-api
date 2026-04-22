
from ninja import Router

from .models import AnalyticalTag, Theme
from .schemas import AnalyticalTagSchema, ThemeSchema

router = Router()


@router.get("/themes", response=list[ThemeSchema])
def list_themes(request):
    return Theme.objects.all().order_by("name")


@router.get("/tags", response=list[AnalyticalTagSchema])
def list_tags(request):
    return AnalyticalTag.objects.all().order_by("name")
