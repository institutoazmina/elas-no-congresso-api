from decouple import config
from django.contrib import admin
from django.urls import path

from config.api import api
from config.health import liveness, readiness

# Admin path is configurable so it can be moved off the obvious /admin/ in prod.
ADMIN_URL = config("ADMIN_URL", default="admin/")

urlpatterns = [
    path(ADMIN_URL, admin.site.urls),
    path("api/v1/", api.urls),
    path("health/", liveness),
    path("health/ready/", readiness),
]
