from unittest.mock import Mock

import httpx
import pytest

from apps.ingestion import fulltext


class _FakePage:
    def __init__(self, text):
        self._text = text

    def extract_text(self):
        return self._text


class _FakeReader:
    def __init__(self, pages):
        self.pages = pages


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler), base_url="https://x")


def _ok_pdf(request):
    return httpx.Response(200, content=b"%PDF-fake-bytes")


class TestExtractPdfText:
    def test_empty_url_returns_none(self):
        assert fulltext.extract_pdf_text(None) is None
        assert fulltext.extract_pdf_text("") is None

    def test_extracts_and_joins_pages(self, monkeypatch):
        monkeypatch.setattr(
            fulltext, "PdfReader", lambda buf: _FakeReader([_FakePage("Ola "), _FakePage("Mundo")])
        )
        text = fulltext.extract_pdf_text("https://x/doc.pdf", client=_client(_ok_pdf))
        # páginas agora são separadas por "\n" (evita grudar palavras entre páginas)
        assert text == "Ola\nMundo"

    def test_no_extractable_text_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            fulltext, "PdfReader", lambda buf: _FakeReader([_FakePage(None), _FakePage("")])
        )
        assert fulltext.extract_pdf_text("https://x/doc.pdf", client=_client(_ok_pdf)) is None

    def test_http_error_returns_none(self, monkeypatch):
        monkeypatch.setattr(fulltext, "PdfReader", lambda buf: _FakeReader([_FakePage("x")]))

        def handler(request):
            return httpx.Response(500)

        assert fulltext.extract_pdf_text("https://x/doc.pdf", client=_client(handler)) is None

    def test_transport_error_returns_none(self):
        def handler(request):
            raise httpx.ConnectError("boom")

        assert fulltext.extract_pdf_text("https://x/doc.pdf", client=_client(handler)) is None

    def test_pdf_parse_error_returns_none(self, monkeypatch):
        def boom(buf):
            raise ValueError("corrupt pdf")

        monkeypatch.setattr(fulltext, "PdfReader", boom)
        assert fulltext.extract_pdf_text("https://x/doc.pdf", client=_client(_ok_pdf)) is None

    def test_extracts_rtf_text(self):
        content = rb"{\rtf1\ansi\ansicpg1252 Prote\'e7\'e3o \b para mulheres\b0.}"
        with _client(lambda request: httpx.Response(200, content=content)) as client:
            text = fulltext.extract_pdf_text(
                "https://x/documento",
                client=client,
                raise_on_unsupported=True,
            )
        assert text == "Proteção para mulheres."

    def test_rtf_parse_error_remains_retryable(self, monkeypatch):
        monkeypatch.setattr(fulltext, "rtf_to_text", Mock(side_effect=ValueError("corrupt rtf")))
        with _client(lambda request: httpx.Response(200, content=rb"{\rtf1 corrupt")) as client:
            assert (
                fulltext.extract_pdf_text(
                    "https://x/documento",
                    client=client,
                    raise_on_unsupported=True,
                )
                is None
            )

    def test_unknown_document_format_is_unsupported(self):
        with (
            _client(lambda request: httpx.Response(200, content=b"not a document")) as client,
            pytest.raises(fulltext.UnsupportedDocumentError),
        ):
            fulltext.extract_pdf_text(
                "https://x/documento",
                client=client,
                raise_on_unsupported=True,
            )

    def test_owns_client_path(self, monkeypatch):
        # Sem client injetado: cria e fecha o próprio httpx.Client.
        monkeypatch.setattr(fulltext, "PdfReader", lambda buf: _FakeReader([_FakePage("ok")]))

        class _DummyClient:
            def __init__(self, *a, **k):
                pass

            def get(self, url):
                return httpx.Response(200, content=b"%PDF", request=httpx.Request("GET", url))

            def close(self):
                self.closed = True

        monkeypatch.setattr(fulltext.httpx, "Client", _DummyClient)
        assert fulltext.extract_pdf_text("https://x/doc.pdf") == "ok"


@pytest.mark.parametrize("url", ["", None])
def test_falsy_urls(url):
    assert fulltext.extract_pdf_text(url) is None


@pytest.mark.parametrize("status", [200, 403, 429, 503])
@pytest.mark.parametrize(
    "page",
    [
        "<!DOCTYPE html><title>Verificação de segurança — Senado Federal</title>",
        "<html><body>Please verify you are human</body></html>",
        '<html><div class="g-recaptcha">Confirm access</div></html>',
    ],
)
def test_security_challenge_is_distinguished_from_pdf_failure(monkeypatch, status, page):
    parse = Mock()
    monkeypatch.setattr(fulltext, "_extract", parse)
    with _client(lambda request: httpx.Response(status, text=page)) as client:
        with pytest.raises(fulltext.DocumentSecurityChallengeError):
            fulltext.extract_pdf_text("https://x/doc.pdf", client=client, raise_on_challenge=True)
        assert fulltext.extract_pdf_text("https://x/doc.pdf", client=client) is None
    parse.assert_not_called()


def test_unrelated_html_remains_extraction_failure():
    with _client(
        lambda request: httpx.Response(200, text="<html>Document not found</html>")
    ) as client:
        assert (
            fulltext.extract_pdf_text("https://x/doc.pdf", client=client, raise_on_challenge=True)
            is None
        )


def test_pdf_about_captcha_is_not_a_security_challenge(monkeypatch):
    parse = Mock(return_value="Legislação sobre CAPTCHA")
    monkeypatch.setattr(fulltext, "_extract", parse)
    with _client(
        lambda request: httpx.Response(200, content=b"%PDF-1.7 captcha verify you are human")
    ) as client:
        assert (
            fulltext.extract_pdf_text("https://x/doc.pdf", client=client, raise_on_challenge=True)
            == parse.return_value
        )
    parse.assert_called_once()
