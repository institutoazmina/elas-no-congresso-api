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
        assert text == "Ola Mundo"

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
