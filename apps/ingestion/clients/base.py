"""Helper HTTP compartilhado pelos clients de coleta.

Usa httpx (síncrono, dentro de Celery tasks) com retry exponencial via tenacity.
Mantém uma única conexão keep-alive por client para reduzir overhead de rede.
"""

import logging

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

_USER_AGENT = "elas-no-congresso-api/ingestion (+https://elasnocongresso.com.br)"
_TIMEOUT = httpx.Timeout(30.0, connect=10.0)

_RETRYABLE = (httpx.TransportError, httpx.HTTPStatusError)


class BaseClient:
    """Cliente HTTP base. Subclasses definem ``base_url``."""

    base_url: str = ""

    def __init__(self, client: httpx.Client | None = None):
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=self.base_url,
            timeout=_TIMEOUT,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
        )

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def close(self):
        if self._owns_client:
            self._client.close()

    @retry(
        retry=retry_if_exception_type(_RETRYABLE),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def get_json(self, url: str, params: dict | None = None) -> dict:
        resp = self._client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()
