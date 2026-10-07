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

    def test_trabalho_is_now_standalone(self):
        # O novo vocabulário inclui TRABALHO isoladamente.
        assert assert_theme("Projeto sobre trabalho rural")["row_relevant"] is True
        # Continua relevante com outros termos.
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


@pytest.mark.parametrize(
    "text",
    [
        "Soja transgenica",
        "Soja transgênica",
        "transgenero",
        "transportes",
        "abortivos",
        "absorventes",
        "mamadeira",
    ],
)
def test_no_partial_words(text):
    assert assert_theme(text)["row_relevant"] is False


@pytest.mark.parametrize("text", ["AbOrTiVo", "ABSORVENTE", "mulheres", "FEMININA", "LGBTQIA+."])
def test_expanded_vocabulary(text):
    assert assert_theme(text)["row_relevant"] is True
