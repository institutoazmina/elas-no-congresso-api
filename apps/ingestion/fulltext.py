"""Extração de texto do inteiro teor (PDF).

Porta utils_inteiroteor.textfrompdf do bot, trocando requests+PyPDF2 por
httpx+pypdf e devolvendo ``None`` em falha (em vez de strings de erro).
Não faz inferência de ML — apenas baixa e extrai o texto.
"""

import io
import logging

import httpx
from pypdf import PdfReader

logger = logging.getLogger(__name__)

_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    )
}


def extract_pdf_text(url: str | None, client: httpx.Client | None = None) -> str | None:
    """Baixa o PDF em ``url`` e extrai o texto. Retorna ``None`` em qualquer falha.

    Args:
        url: URL do inteiro teor. Vazio/None → None.
        client: httpx.Client opcional (injetável para testes/reuso de conexão).
    """
    if not url:
        return None

    own = client is None
    client = client or httpx.Client(timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True)
    try:
        resp = client.get(url)
        resp.raise_for_status()
        content = resp.content
    except httpx.HTTPError as exc:
        logger.warning("Falha ao baixar PDF %s: %s", url, exc)
        return None
    finally:
        if own:
            client.close()

    try:
        reader = PdfReader(io.BytesIO(content))
        text = "".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:  # noqa: BLE001 — pypdf lança vários tipos de erro
        logger.warning("Falha ao ler PDF %s: %s", url, exc)
        return None

    return text or None
