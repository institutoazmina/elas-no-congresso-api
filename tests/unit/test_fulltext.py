from apps.ingestion import fulltext


class _FakePage:
    def __init__(self, text):
        self._text = text

    def extract_text(self):
        return self._text


class _FakeReader:
    def __init__(self, *pages):
        self.pages = [_FakePage(p) for p in pages]


def _patch(monkeypatch, *pages):
    """Isola _extract da rede e do OCR: só o caminho pypdf."""
    monkeypatch.setattr(fulltext, "PdfReader", lambda _stream: _FakeReader(*pages))
    monkeypatch.setattr(fulltext, "_open_fitz", lambda _content: None)


class TestExtractNulBytes:
    def test_nul_is_stripped(self, monkeypatch):
        """Postgres recusa NUL em text; o pypdf emite \\x00 em PDF com encoding
        quebrado (visto no PDL 20/2024). Sem remover, _persist estoura DataError."""
        _patch(monkeypatch, "NT44/2022\x00\nARecomendação")
        out = fulltext._extract(b"%PDF-fake")
        assert "\x00" not in out
        assert out == "NT44/2022\nARecomendação"

    def test_nul_stripped_across_pages(self, monkeypatch):
        _patch(monkeypatch, "pag\x00um", "pag\x00dois")
        assert fulltext._extract(b"%PDF-fake") == "pagum\npagdois"

    def test_text_without_nul_is_untouched(self, monkeypatch):
        _patch(monkeypatch, "texto normal")
        assert fulltext._extract(b"%PDF-fake") == "texto normal"

    def test_only_nul_becomes_none(self, monkeypatch):
        """Página só com NUL vira vazio -> None (nada de full_text='')."""
        _patch(monkeypatch, "\x00")
        assert fulltext._extract(b"%PDF-fake") is None

    def test_unreadable_pdf_returns_none(self, monkeypatch):
        def _boom(_stream):
            raise ValueError("pdf corrompido")

        monkeypatch.setattr(fulltext, "PdfReader", _boom)
        assert fulltext._extract(b"nao-e-pdf") is None
