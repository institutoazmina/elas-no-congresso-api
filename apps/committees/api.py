
from ninja import Router
from ninja.pagination import LimitOffsetPagination, paginate

from .models import Committee
from .schemas import CommitteeSchema

router = Router()


@router.get("", response=list[CommitteeSchema])
@paginate(LimitOffsetPagination)
def list_committees(request, house: str | None = None, active: bool | None = None):
    qs = Committee.objects.all()
    if house:
        qs = qs.filter(house=house)
    if active is not None:
        qs = qs.filter(is_active=active)
    return qs.order_by("acronym")
