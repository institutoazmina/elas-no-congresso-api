from django.http import HttpResponse
from ninja import Router

from .models import AlertsPage
from .schemas import AlertsPageSchema

router = Router()


def _image(field, width, height, version):
    # Dimensões gravadas no upload: ler `field.width` baixaria o arquivo.
    # O arquivo é sempre o mesmo; `?v=` faz o navegador buscar a versão nova.
    return {"url": f"{field.url}?v={version}", "width": width, "height": height}


@router.get("/alerts", response=AlertsPageSchema)
def alerts_page(request, response: HttpResponse):
    """Conteúdo editável da página de alertas, lido pelo build do site.

    Sem cache: o build disparado por um salvamento precisa ler a versão nova.
    """
    response["Cache-Control"] = "no-store"
    page = AlertsPage.current()
    return {
        "title": page.title,
        "subtitle": page.subtitle,
        "hero_image": _image(
            page.hero_image,
            page.hero_image_width,
            page.hero_image_height,
            int(page.updated_at.timestamp()) if page.updated_at else 0,
        ),
    }
