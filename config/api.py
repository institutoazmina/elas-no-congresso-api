from ninja import NinjaAPI
from ninja.pagination import LimitOffsetPagination, paginate  # noqa: F401

api = NinjaAPI(
    version="1.0.0",
    title="Elas no Congresso API",
    description="API pública de dados legislativos com foco em gênero e diversidade.",
    docs_url="/docs",
)


def register_routers() -> None:
    from apps.committees.api import router as committees_router
    from apps.legislatures.api import router as legislatures_router
    from apps.norms.api import router as norms_router
    from apps.propositions.api import router as propositions_router
    from apps.propositions.dataset import router as dataset_router
    from apps.subscriptions.api import router as subscriptions_router
    from apps.taxonomy.api import router as taxonomy_router

    api.add_router("/legislatures/", legislatures_router, tags=["Legislaturas"])
    api.add_router("/propositions/", propositions_router, tags=["Proposições"])
    api.add_router("/dataset/", dataset_router, tags=["Dataset"])
    api.add_router("/taxonomy/", taxonomy_router, tags=["Taxonomia"])
    api.add_router("/committees/", committees_router, tags=["Comissões"])
    api.add_router("/norms/", norms_router, tags=["Normas"])
    api.add_router("/subscriptions/", subscriptions_router, tags=["Inscrições"])


register_routers()
