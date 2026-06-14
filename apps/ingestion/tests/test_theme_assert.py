import pytest

from apps.ingestion.theme_assert import assert_theme

# assert_theme consulta o banco (cai nos defaults quando vazio).
pytestmark = pytest.mark.django_db


class TestAssertTheme:
    def test_standalone_match(self):
        res = assert_theme("Projeto sobre violência contra a mulher")
        assert res["row_relevant"] is True
        assert any("mulher" in t.lower() for t in res["temas"])

    def test_case_insensitive(self):
        assert assert_theme("FEMINICÍDIO no estado")["row_relevant"] is True

    def test_combined_requires_mulher(self):
        # "trabalho" sozinho não basta…
        assert assert_theme("Projeto sobre trabalho rural")["row_relevant"] is False
        # …mas com "mulher" no texto, vira relevante.
        assert assert_theme("Trabalho da mulher no campo")["row_relevant"] is True

    def test_irrelevant(self):
        assert assert_theme("Pavimentação asfáltica de rodovia")["row_relevant"] is False

    def test_empty_and_none(self):
        assert assert_theme("")["row_relevant"] is False
        assert assert_theme(None)["row_relevant"] is False
        assert assert_theme(None, None)["temas"] == []

    def test_multiple_fields_joined(self):
        res = assert_theme("Texto neutro", None, "aborto legal")
        assert res["row_relevant"] is True
