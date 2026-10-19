from django.db import models
from django.http import HttpResponse
from ninja import Router

from .models import (
    AboutPage,
    ActivityPage,
    AlertsPage,
    FeministAIPage,
    FooterAlertsPage,
    HeroPage,
    HomePage,
    ReportsPage,
)
from .schemas import (
    AboutPageSchema,
    FeministAIPageSchema,
    FooterAlertsPageSchema,
    HeroPageSchema,
    HomePageSchema,
)

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


@router.get("/about", response=AboutPageSchema)
def about_page(request, response: HttpResponse):
    """Textos e marcos da página Sobre, lidos pelo build do site."""
    response["Cache-Control"] = "no-store"
    page = AboutPage.objects.prefetch_related("copy", "timeline", "challenges", "partners").get(
        pk=AboutPage.SINGLETON_PK
    )
    version = int(page.updated_at.timestamp())
    return {
        "content": {
            "seo_title": page.seo_title,
            "seo_description": page.seo_description,
            "timeline_note_link_text": page.timeline_note_link_text,
            "timeline_note_link_url": page.timeline_note_link_url,
            "timeline_note_after_link": page.timeline_note_after_link,
            **{item.key: item.value for item in page.copy.all()},
        },
        "hero_image": _cms_image(
            page.hero_image, page.hero_image_width, page.hero_image_height, version
        ),
        "timeline": _items(
            page,
            "timeline",
            "date_prefix",
            "year",
            "description_before_link",
            "link_text",
            "link_url",
            "description_after_link",
            "tag",
        ),
        "challenges": _items(page, "challenges", "title", "text"),
        "partners": [
            {
                "name": partner.name,
                "asset_key": partner.asset_key,
                "logo_url": f"{partner.logo_image.url}?v={version}" if partner.logo_image else "",
            }
            for partner in page.partners.all()
        ],
    }


@router.get("/home", response=HomePageSchema)
def home_page(request, response: HttpResponse):
    """Conteúdo editorial da home; gráficos, cards e mapas usam as APIs próprias."""
    response["Cache-Control"] = "no-store"
    page = HomePage.objects.prefetch_related("copy").get(pk=HomePage.SINGLETON_PK)
    version = int(page.updated_at.timestamp())
    return {
        "content": {item.key: item.value for item in page.copy.all()},
        "images": {
            "hero": _cms_image(
                page.hero_image, page.hero_image_width, page.hero_image_height, version
            ),
            "explore": _cms_image(
                page.explore_image, page.explore_image_width, page.explore_image_height, version
            ),
            "quiteria": _cms_image(
                page.quiteria_image, page.quiteria_image_width, page.quiteria_image_height, version
            ),
        },
    }


@router.get("/footer-alerts", response=FooterAlertsPageSchema)
def footer_alerts_page(request, response: HttpResponse):
    """Chamada compartilhada no rodapé de todas as páginas."""
    response["Cache-Control"] = "no-store"
    page = FooterAlertsPage.current()
    return {
        "title": page.title,
        "text": page.text,
        "cta_text": page.cta_text,
        "cta_url": page.cta_url,
    }
