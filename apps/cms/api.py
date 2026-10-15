from django.http import HttpResponse
from ninja import Router

from .models import ActivityPage, AlertsPage, HeroPage, ReportsPage
from .schemas import HeroPageSchema

router = Router()


def _hero(model: type[HeroPage], response: HttpResponse) -> dict:
    # Sem cache: o build disparado por um salvamento precisa ler a versão nova.
    response["Cache-Control"] = "no-store"
    page = model.current()
    version = int(page.updated_at.timestamp()) if page.updated_at else 0
    return {
        "title": page.title,
        "subtitle": page.subtitle,
        # Dimensões gravadas no upload: ler `hero_image.width` baixaria o arquivo.
        # O arquivo é sempre o mesmo; `?v=` faz o navegador buscar a versão nova.
        "hero_image": {
            "url": f"{page.hero_image.url}?v={version}",
            "width": page.hero_image_width,
            "height": page.hero_image_height,
        },
    }


@router.get("/alerts", response=HeroPageSchema)
def alerts_page(request, response: HttpResponse):
    """Topo editável da página de alertas, lido pelo build do site."""
    return _hero(AlertsPage, response)


@router.get("/reports", response=HeroPageSchema)
def reports_page(request, response: HttpResponse):
    """Topo editável da página de reportagens, lido pelo build do site."""
    return _hero(ReportsPage, response)


@router.get("/activity", response=HeroPageSchema)
def activity_page(request, response: HttpResponse):
    """Topo editável da página de atividade legislativa, lido pelo build do site."""
    return _hero(ActivityPage, response)
