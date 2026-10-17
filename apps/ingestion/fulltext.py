"""Extração de texto do inteiro teor (PDF), com OCR de fallback por página.

O pypdf extrai a camada de texto. Quando uma página vem "fina" (o conteúdo é
imagem — comum nos PDFs da Câmara/InfoLeg, onde o texto da proposição é uma
imagem com brasão de fundo, e o pypdf só enxerga o cabeçalho de autenticação),
roda Tesseract: PyMuPDF renderiza a página → pytesseract (idioma ``por``). Assim
recupera artigos/justificativa que o pypdf perderia, SEM OCR-ar páginas que já
têm texto (mais rápido e sem o ruído dos carimbos de assinatura).

Se o OCR não estiver disponível (sem tesseract/fitz), degrada para só-pypdf.
"""

import io
import logging
import os
import re
import unicodedata
from html import unescape

import httpx
from pypdf import PdfReader

logger = logging.getLogger(__name__)

# No container distroless o binário fica em /usr/bin/tesseract (via env);
# localmente (macOS/Homebrew) fica no PATH e a env não é setada.
_TESSERACT_CMD = os.environ.get("TESSERACT_CMD")

_TIMEOUT = httpx.Timeout(60.0, connect=10.0)
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    )
}

# Página com menos texto (pypdf) que isto é candidata a OCR (provável imagem).
_OCR_MIN_CHARS = 500
# Só adota o OCR se ele acrescentar conteúdo substancial sobre o pypdf.
_OCR_GAIN_MIN = 200
# 200 DPI: pixmap ~pela metade de 300 — evita OOM no worker (512m). Qualidade
# de OCR ainda boa para os PDFs legislativos.
_OCR_DPI = 200
_OCR_LANG = "por"


class DocumentSecurityChallengeError(Exception):
    """The document endpoint requires interactive security verification."""


def _is_security_challenge(response: httpx.Response) -> bool:
    prefix = response.content[:65536]
    if prefix.lstrip().startswith(b"%PDF-"):
        return False
    html = prefix.decode("utf-8", errors="replace").lower()
    if not re.search(r"<!doctype\s+html|<html\b|<head\b|<body\b", html):
        return False
    text = unicodedata.normalize("NFKD", unescape(html)).encode("ascii", "ignore").decode()
    return any(
        marker in text
        for marker in (
            "verificacao de seguranca",
            "captcha",
            "verify you are human",
            "verify that you are human",
            "verifique que voce e humano",
            "checking your browser",
            "cf-chl-",
            "cf-turnstile",
        )
    )


def extract_pdf_text(
    url: str | None, client: httpx.Client | None = None, *, raise_on_challenge: bool = False
) -> str | None:
    """Baixa o PDF em ``url`` e extrai o texto (pypdf + OCR nas páginas-imagem).

    Retorna ``None`` em falhas de download/leitura. Com ``raise_on_challenge``,
    sinaliza verificação interativa separadamente para a descoberta usar a ementa.
    """
    if not url:
        return None

    own = client is None
    client = client or httpx.Client(timeout=_TIMEOUT, headers=_HEADERS, follow_redirects=True)
    try:
        resp = client.get(url)
        # Challenges can arrive as HTTP 200 as well as 403/429/503 responses.
        if _is_security_challenge(resp):
            if raise_on_challenge:
                raise DocumentSecurityChallengeError("Document requires security verification")
            return None
        resp.raise_for_status()
        content = resp.content
    except httpx.HTTPError as exc:
        logger.warning("Falha ao baixar PDF %s: %s", url, exc)
        return None
    finally:
        if own:
            client.close()

    return _extract(content, url)


def _extract(content: bytes, url: str = "") -> str | None:
    try:
        pages = PdfReader(io.BytesIO(content)).pages
    except Exception as exc:  # noqa: BLE001 — pypdf lança vários tipos
        logger.warning("Falha ao ler PDF %s: %s", url, exc)
        return None

    doc = _open_fitz(content)  # None → OCR indisponível, segue só com pypdf
    parts: list[str] = []
    for i, page in enumerate(pages):
        try:
            text = (page.extract_text() or "").strip()
        except Exception:  # noqa: BLE001
            text = ""
        if doc is not None and len(text) < _OCR_MIN_CHARS:
            ocr = _ocr_page(doc, i)
            if ocr and len(ocr) > len(text) + _OCR_GAIN_MIN:
                logger.info(
                    "OCR pág %d: pypdf=%d → ocr=%d chars (%s)",
                    i + 1,
                    len(text),
                    len(ocr),
                    url[:60],
                )
                text = ocr
        parts.append(text)
    if doc is not None:
        doc.close()

    # Postgres recusa NUL (0x00) em campo text, e o pypdf emite \x00 quando o
    # PDF tem mapa de encoding quebrado — sem isto o _persist estoura DataError
    # e a proposição inteira se perde.
    return "\n".join(parts).replace("\x00", "").strip() or None


def _open_fitz(content: bytes):
    try:
        import fitz  # PyMuPDF

        return fitz.open(stream=content, filetype="pdf")
    except Exception as exc:  # noqa: BLE001 — sem OCR, cai no pypdf puro
        logger.debug("OCR indisponível (fitz): %s", exc)
        return None


def _ocr_page(doc, index: int) -> str | None:
    try:
        import pytesseract
        from PIL import Image

        if _TESSERACT_CMD:
            pytesseract.pytesseract.tesseract_cmd = _TESSERACT_CMD
        pix = doc[index].get_pixmap(dpi=_OCR_DPI)
        png = pix.tobytes("png")
        pix = None  # libera o pixmap (memória C do PyMuPDF) o quanto antes
        with Image.open(io.BytesIO(png)) as img:
            return pytesseract.image_to_string(img, lang=_OCR_LANG).strip()
    except Exception as exc:  # noqa: BLE001 — OCR é best-effort
        logger.warning("OCR falhou na página %d: %s", index, exc)
        return None
