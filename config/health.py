"""Lightweight health endpoints for orchestrator probes.

- ``/health/``       liveness  — the process is up and serving HTTP.
- ``/health/ready/`` readiness — DB and Redis are reachable.

Kept dependency-free (plain Django views) so a probe never drags in the
full API stack.
"""

from django.db import connections
from django.db.utils import OperationalError
from django.http import JsonResponse
from django.views.decorators.cache import never_cache


@never_cache
def liveness(request):
    return JsonResponse({"status": "ok"})


@never_cache
def readiness(request):
    checks = {}

    # Database
    try:
        connections["default"].cursor().execute("SELECT 1")
        checks["database"] = "ok"
    except OperationalError as exc:
        checks["database"] = f"error: {exc}"

    # Redis cache
    try:
        from django.core.cache import cache

        cache.set("healthcheck", "1", timeout=5)
        checks["cache"] = "ok" if cache.get("healthcheck") == "1" else "error: readback failed"
    except Exception as exc:  # noqa: BLE001 — surface any backend error as unhealthy
        checks["cache"] = f"error: {exc}"

    healthy = all(v == "ok" for v in checks.values())
    return JsonResponse(
        {"status": "ready" if healthy else "unavailable", "checks": checks},
        status=200 if healthy else 503,
    )
