"""Custom middleware."""

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
