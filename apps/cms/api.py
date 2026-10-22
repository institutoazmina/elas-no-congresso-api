from django.http import HttpResponse
from ninja import Router

from .models import (
    AboutPage,
    AboutTeamMember,
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
        "seo_title": page.seo_title,
        "seo_description": page.seo_description,
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
    page = FeministAIPage.objects.get(pk=FeministAIPage.SINGLETON_PK)
    version = int(page.updated_at.timestamp())
    content = page.content
    for image in [page.flow_desktop_image, page.flow_mobile_image]:
        content = content.replace(
            f"/media/{image.name}",
            f"{image.url}?v={version}",
        )
    return {
        "seo_title": page.seo_title,
        "seo_description": page.seo_description,
        "title": page.hero_title,
        "subtitle": page.hero_description,
        "hero_image": _cms_image(
            page.hero_image, page.hero_image_width, page.hero_image_height, version
        ),
        "content": content,
    }


@router.get("/about", response=AboutPageSchema)
def about_page(request, response: HttpResponse):
    """Hero, Markdown e organizações parceiras da página Sobre."""
    response["Cache-Control"] = "no-store"
    page = AboutPage.objects.prefetch_related("partners", "team_members").get(
        pk=AboutPage.SINGLETON_PK
    )
    version = int(page.updated_at.timestamp())
    team_members = list(page.team_members.all())
    return {
        "seo_title": page.seo_title,
        "seo_description": page.seo_description,
        "title": page.hero_title,
        "subtitle": page.hero_description,
        "hero_image": _cms_image(
            page.hero_image, page.hero_image_width, page.hero_image_height, version
        ),
        "content": page.content,
        "partners": [
            {
                "name": partner.name,
                "logo_url": f"{partner.logo_image.url}?v={version}",
            }
            for partner in page.partners.all()
        ],
        "team": [
            {
                "key": key,
                "title": title,
                "wide": key == AboutTeamMember.Group.PREVIOUS,
                "members": [
                    {"name": member.name, "role": member.role}
                    for member in team_members
                    if member.group == key
                ],
            }
            for key, title in AboutTeamMember.Group.choices
            if any(member.group == key for member in team_members)
        ],
    }


@router.get("/home", response=HomePageSchema)
def home_page(request, response: HttpResponse):
    """Hero e Markdown da Home; gráficos usam as APIs próprias."""
    response["Cache-Control"] = "no-store"
    page = HomePage.objects.get(pk=HomePage.SINGLETON_PK)
    version = int(page.updated_at.timestamp())
    return {
        "seo_title": page.seo_title,
        "seo_description": page.seo_description,
        "title": page.hero_title,
        "subtitle": page.hero_description,
        "cta_text": page.hero_cta_text,
        "cta_url": "#o-que-descobrimos",
        "hero_image": _cms_image(
            page.hero_image, page.hero_image_width, page.hero_image_height, version
        ),
        "content": page.content,
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
