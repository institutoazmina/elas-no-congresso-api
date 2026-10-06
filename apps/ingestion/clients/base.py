"""Helper HTTP compartilhado pelos clients de coleta.

Usa httpx (síncrono, dentro de Celery tasks) com retry exponencial via tenacity.
Mantém uma única conexão keep-alive por client para reduzir overhead de rede.
"""

import logging
import random
import time
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit

import httpx
from django.conf import settings
from django.core.cache import cache
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)

_USER_AGENT = "elas-no-congresso-api/ingestion (+https://elasnocongresso.com.br)"
_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


def _retryable(exc):
    return isinstance(exc, httpx.TransportError) or (
        isinstance(exc, httpx.HTTPStatusError)
        and (exc.response.status_code == 429 or exc.response.status_code >= 500)
    )


def _retry_wait(state):
    error = state.outcome.exception()
    if isinstance(error, httpx.HTTPStatusError):
        value = error.response.headers.get("Retry-After")
        if value:
            try:
                seconds = float(value)
            except ValueError:
                try:
                    seconds = parsedate_to_datetime(value).timestamp() - time.time()
                except (ValueError, TypeError, OverflowError):
                    seconds = 0
            if seconds > 0:
                return min(seconds, 60)
    return wait_exponential(multiplier=1, min=2, max=30)(state) + random.uniform(0, 1)


def throttle_source(source):
    rate = settings.INGESTION_REQUESTS_PER_SECOND
    if rate <= 0:
        return
    # Redis shares the slots across workers and reconciliation jobs.
    while True:
        now = time.time()
        slot = int(now * rate)
        if cache.add(f"ingestion:http:{source}:{slot}", True, timeout=max(2, 2 / rate)):
            return
        time.sleep(max(0.01, (slot + 1) / rate - now))


class BaseClient:
    """Cliente HTTP base. Subclasses definem ``base_url``."""

    base_url: str = ""

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        timeout: httpx.Timeout = _TIMEOUT,
        accept: str = "application/json",
    ):
        self._owns_client = client is None
        self._client = client or httpx.Client(
            base_url=self.base_url,
            timeout=timeout,
            headers={"User-Agent": _USER_AGENT, "Accept": accept},
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
        retry=retry_if_exception(_retryable),
        wait=_retry_wait,
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def get_json(self, url: str, params: dict | None = None) -> dict:
        throttle_source(urlsplit(self.base_url).netloc or self.base_url)
        resp = self._client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()
