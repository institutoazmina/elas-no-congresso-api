from django.db import models
from django.http import HttpResponse
from ninja import Router

from .models import ActivityPage, AlertsPage, FeministAIPage, HeroPage, ReportsPage
from .schemas import FeministAIPageSchema, HeroPageSchema

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


def _cms_image(field, width: int, height: int, version: int) -> dict:
    return {"url": f"{field.url}?v={version}", "width": width, "height": height}


def _items(page, relation: str, *fields: str) -> list[dict]:
    return [
        {field: getattr(item, field) for field in fields} for item in getattr(page, relation).all()
    ]


@router.get("/feminist-ai", response=FeministAIPageSchema)
def feminist_ai_page(request, response: HttpResponse):
    """Conteúdo editável da página QuitérIA, lido pelo build do site."""
    response["Cache-Control"] = "no-store"
    page = FeministAIPage.objects.prefetch_related(
        "feministaicategory_set",
        "feministailimitation_set",
        "feministaievaluationmetric_set",
        "feministaievaluationpartition_set",
        "feministaithematicmetric_set",
        "feministaithematicpartition_set",
        "feministaiopenlink_set",
    ).get(pk=FeministAIPage.SINGLETON_PK)
    version = int(page.updated_at.timestamp())
    excluded = {"id", "updated_at"}
    content = {
        field.name: getattr(page, field.name)
        for field in page._meta.fields
        if field.name not in excluded and isinstance(field, (models.CharField, models.TextField))
    }
    return {
        "content": content,
        "images": {
            "hero": _cms_image(
                page.hero_image, page.hero_image_width, page.hero_image_height, version
            ),
            "flow_desktop": _cms_image(
                page.flow_desktop_image, page.flow_desktop_width, page.flow_desktop_height, version
            ),
            "flow_mobile": _cms_image(
                page.flow_mobile_image, page.flow_mobile_width, page.flow_mobile_height, version
            ),
        },
        "categories": _items(page, "feministaicategory_set", "name", "concept"),
        "limitations": _items(page, "feministailimitation_set", "text"),
        "evaluation_metrics": _items(
            page, "feministaievaluationmetric_set", "label", "url", "previous", "current", "trend"
        ),
        "evaluation_partitions": _items(
            page, "feministaievaluationpartition_set", "label", "accuracy", "percentage", "count"
        ),
        "thematic_metrics": _items(page, "feministaithematicmetric_set", "label", "value"),
        "thematic_partitions": _items(
            page, "feministaithematicpartition_set", "label", "training", "validation", "test"
        ),
        "open_links": _items(page, "feministaiopenlink_set", "label", "url"),
    }
