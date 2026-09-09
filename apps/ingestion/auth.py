import secrets

from django.conf import settings
from ninja.security import HttpBearer


class ParliamentarianEnrichmentBearerAuth(HttpBearer):
    def authenticate(self, request, token):
        configured_token = getattr(settings, "PARLIAMENTARIAN_ENRICHMENT_API_TOKEN", "")
        if not isinstance(configured_token, str) or not configured_token:
            return None

        if secrets.compare_digest(token, configured_token):
            return True
        return None


parliamentarian_enrichment_auth = ParliamentarianEnrichmentBearerAuth()
