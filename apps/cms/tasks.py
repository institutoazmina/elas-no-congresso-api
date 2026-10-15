import httpx
from celery import shared_task
from django.conf import settings
from django.core.cache import cache

from .deploy import RetryableDispatchError, dispatch_site_deploy

PENDING_KEY = "cms:site-deploy:pending"


def enqueue_site_deploy() -> None:
    """Agenda um deploy do site, agrupando os salvamentos da mesma janela."""
    if not settings.SITE_DEPLOY_GITHUB_TOKEN:
        return
    delay = settings.SITE_DEPLOY_DELAY_SECONDS
    if cache.add(PENDING_KEY, 1, timeout=delay + 60):
        request_site_deploy.apply_async(countdown=delay)


@shared_task(
    autoretry_for=(httpx.TransportError, RetryableDispatchError),
    retry_backoff=True,
    max_retries=5,
)
def request_site_deploy() -> None:
    # Liberado antes da chamada: um salvamento durante o envio agenda outro deploy.
    cache.delete(PENDING_KEY)
    dispatch_site_deploy()
