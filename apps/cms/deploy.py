"""Dispara o deploy do site quando o conteúdo do CMS muda.

O workflow ``Build & Deploy`` do site escuta ``repository_dispatch`` e roda um
deploy por vez; o build lê o conteúdo mais recente da API quando começa.
"""

import httpx
from django.conf import settings

EVENT_TYPE = "cms-content-updated"
TIMEOUT_SECONDS = 15


class RetryableDispatchError(Exception):
    """Falha transitória do GitHub (429 ou 5xx): vale tentar de novo."""


def dispatch_site_deploy() -> None:
    response = httpx.post(
        f"https://api.github.com/repos/{settings.SITE_DEPLOY_GITHUB_REPOSITORY}/dispatches",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {settings.SITE_DEPLOY_GITHUB_TOKEN}",
            "User-Agent": "elas-no-congresso-api",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        json={"event_type": EVENT_TYPE},
        timeout=TIMEOUT_SECONDS,
    )
    if response.status_code == 429 or response.status_code >= 500:
        raise RetryableDispatchError(f"GitHub {response.status_code}")
    response.raise_for_status()
