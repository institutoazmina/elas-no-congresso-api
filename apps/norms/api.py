from typing import Annotated

from ninja import Query, Router
from ninja.pagination import LimitOffsetPagination, paginate

from .models import LegalNorm
from .schemas import LegalNormSchema

router = Router()


@router.get("", response=list[LegalNormSchema])
@paginate(LimitOffsetPagination)
def list_norms(
    request,
    type: str | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,  # type: ignore[operator]
):
    qs = LegalNorm.objects.all()
    if type:
        qs = qs.filter(type=type)
    if q:
        qs = qs.filter(official_name__icontains=q)
    return qs.order_by("-year", "type")
