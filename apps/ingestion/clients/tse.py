"""HTTP client for the official TSE candidate archive."""

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from apps.ingestion.tse import TSEArchiveLimitError

from .base import BaseClient

TSE_ARCHIVE_URLS = {
    2018: "https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_2018.zip",
    2022: "https://cdn.tse.jus.br/estatistica/sead/odsele/consulta_cand/consulta_cand_2022.zip",
}
DEFAULT_TSE_ARCHIVE_URL = TSE_ARCHIVE_URLS[2022]
TSE_ARCHIVE_TIMEOUT = httpx.Timeout(120.0, connect=15.0)
TSE_MAX_DOWNLOAD_BYTES = 128 * 1024 * 1024


class TSEClient(BaseClient):
    base_url = "https://cdn.tse.jus.br"

    def __init__(
        self,
        client: httpx.Client | None = None,
        *,
        archive_url: str = DEFAULT_TSE_ARCHIVE_URL,
        max_download_bytes: int = TSE_MAX_DOWNLOAD_BYTES,
    ):
        super().__init__(client, timeout=TSE_ARCHIVE_TIMEOUT, accept="application/zip")
        self.archive_url = archive_url
        self.max_download_bytes = max_download_bytes

    @retry(
        retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def download_archive(self) -> bytes:
        with self._client.stream(
            "GET",
            self.archive_url,
            headers={"Accept": "application/zip"},
        ) as response:
            response.raise_for_status()
            content_length = response.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > self.max_download_bytes:
                        raise TSEArchiveLimitError("TSE archive exceeds compressed-size limit")
                except ValueError:
                    pass

            payload = bytearray()
            for chunk in response.iter_bytes():
                payload.extend(chunk)
                if len(payload) > self.max_download_bytes:
                    raise TSEArchiveLimitError("TSE archive exceeds compressed-size limit")
            return bytes(payload)
