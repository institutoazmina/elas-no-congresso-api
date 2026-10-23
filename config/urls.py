from decouple import config
from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path

from apps.subscriptions.assets import email_asset
from config.api import api
from config.health import liveness, readiness

# Admin path is configurable so it can be moved off the obvious /admin/ in prod.
ADMIN_URL = config("ADMIN_URL", default="admin/")

urlpatterns = [
    path(ADMIN_URL, admin.site.urls),
    path("api/v1/assets/emails/<str:name>", email_asset, name="email-asset"),
    path("api/v1/", api.urls),
    path("health/", liveness),
    path("health/ready/", readiness),
] + static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
