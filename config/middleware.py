"""Custom middleware."""

from django.conf import settings
from django.utils.cache import patch_cache_control

# Paths probed by the orchestrator (kamal-proxy / Docker HEALTHCHECK).
_HEALTH_PATHS = frozenset({"/health/", "/health/ready/"})


class HealthCheckHostMiddleware:
    """Let orchestrator health probes bypass ALLOWED_HOSTS.

    kamal-proxy probes the health endpoints using the container's ID as the
    Host header (e.g. ``9febfcfbc7cc:8000``), which Django rejects as an
    Invalid HTTP_HOST. The container ID changes every deploy and can't be
    predicted, so for the health paths only we rewrite Host to a fixed allowed
    value. All other traffic keeps the strict ALLOWED_HOSTS check. Must be the
    first middleware so the rewrite happens before host validation.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path in _HEALTH_PATHS:
            request.META["HTTP_HOST"] = "localhost"
        return self.get_response(request)


# Inscrição devolve redirects com token na URL; nunca pode virar cache público.
_PUBLIC_CACHE_PREFIX = "/api/v1/"
_PRIVATE_PREFIXES = ("/api/v1/subscriptions/",)


class PublicCacheControlMiddleware:
    """Marca as leituras públicas da API como cacheáveis por CDN.

    Os dados mudam uma vez por dia, mas sem ``Cache-Control`` o Cloudflare
    repassa toda requisição ao Django. Só respostas 200 de GET/HEAD, sem
    cookie e sem cabeçalho de cache próprio — erro e throttle (429) seguem
    sem cache para não serem servidos a outras pessoas.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if (
            request.method in ("GET", "HEAD")
            and request.path.startswith(_PUBLIC_CACHE_PREFIX)
            and not request.path.startswith(_PRIVATE_PREFIXES)
            and response.status_code == 200
            and not response.cookies
            and not response.has_header("Cache-Control")
        ):
            patch_cache_control(
                response,
                public=True,
                max_age=settings.PUBLIC_CACHE_MAX_AGE,
                s_maxage=settings.PUBLIC_CACHE_S_MAXAGE,
                stale_while_revalidate=settings.PUBLIC_CACHE_STALE_WHILE_REVALIDATE,
            )
        return response
