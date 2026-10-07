import pytest

from apps.ingestion.models import RelevanceTerm
from apps.ingestion.theme_assert import assert_theme, invalidate_cache

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _empty_relevance_terms():
    """Isola os testes de tema da migração de seed (0003_seed_relevance_terms).

    O seed roda na criação do banco de teste (fora da transação do teste), então
    a tabela nunca está vazia — e os defaults do theme_assert jamais seriam
    exercitados. Aqui limpamos a tabela dentro da transação de cada teste
    (revertida ao fim) e invalidamos o cache de termos antes e depois.
    """
    RelevanceTerm.objects.all().delete()
    invalidate_cache()
    yield
    invalidate_cache()


class TestRelevanceTermModel:
    def test_str(self):
        t = RelevanceTerm(term="aborto", mode=RelevanceTerm.Mode.STANDALONE)
        assert "aborto" in str(t)

    def test_admin_registered(self):
        from django.contrib.admin.sites import site

        assert RelevanceTerm in site._registry


class TestThemeFromDatabase:
    def test_empty_table_falls_back_to_defaults(self):
        assert RelevanceTerm.objects.count() == 0  # banco de teste vazio
        assert assert_theme("direitos da mulher")["row_relevant"] is True

    def test_db_terms_override_defaults(self):
        # Com termos no banco, os defaults deixam de valer.
        RelevanceTerm.objects.create(term="jabuticaba", mode=RelevanceTerm.Mode.STANDALONE)
        assert assert_theme("projeto sobre jabuticaba")["row_relevant"] is True
        # "mulher" era default mas não está no banco → não casa mais.
        assert assert_theme("direitos da mulher")["row_relevant"] is False

    def test_inactive_term_ignored(self):
        RelevanceTerm.objects.create(
            term="jabuticaba", mode=RelevanceTerm.Mode.STANDALONE, is_active=False
        )
        # Só há um termo, inativo → tabela "vazia" de ativos → cai nos defaults.
        assert assert_theme("projeto sobre jabuticaba")["row_relevant"] is False
        assert assert_theme("direitos da mulher")["row_relevant"] is True

    def test_combined_mode_requires_mulher(self):
        RelevanceTerm.objects.create(term="orçamento", mode=RelevanceTerm.Mode.COMBINED)
        assert assert_theme("projeto de orçamento")["row_relevant"] is False
        assert assert_theme("orçamento para a mulher")["row_relevant"] is True

    def test_db_error_falls_back_to_defaults(self, monkeypatch):
        # Tabela ausente / erro de banco → usa os defaults, não quebra a coleta.
        def boom(*a, **k):
            raise Exception("db indisponível")

        monkeypatch.setattr(RelevanceTerm.objects, "filter", boom)
        assert assert_theme("direitos da mulher")["row_relevant"] is True

    def test_edit_invalidates_cache_via_signal(self):
        # Primeira chamada popula o cache (defaults).
        assert assert_theme("projeto sobre xpto")["row_relevant"] is False
        # Salvar um termo dispara o signal que limpa o cache.
        RelevanceTerm.objects.create(term="xpto", mode=RelevanceTerm.Mode.STANDALONE)
        assert assert_theme("projeto sobre xpto")["row_relevant"] is True
        # Excluir também invalida.
        RelevanceTerm.objects.filter(term="xpto").delete()
        assert assert_theme("projeto sobre xpto")["row_relevant"] is False


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Combate ao abuso sexual.", True),
        ("ABUSO\n\t SEXUAL", True),
        ("abuso de natureza sexual", False),
        ("abuso sexuais", False),
        ("sexual abuso", False),
    ],
)
def test_complete_phrase(text, expected):
    RelevanceTerm.objects.create(term="ABUSO SEXUAL")
    assert assert_theme(text)["row_relevant"] is expected


def test_phrase_cannot_span_fields():
    RelevanceTerm.objects.create(term="ABUSO SEXUAL")
    assert assert_theme("abuso", "sexual")["row_relevant"] is False


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("LGBTQIA+", True),
        ("LGBTQIA+.", True),
        ("lgbtqia+ no texto", True),
        ("LGBTQIA", False),
        ("LGBTQIA+extra", False),
    ],
)
def test_literal_trailing_plus(text, expected):
    RelevanceTerm.objects.create(term="LGBTQIA+")
    assert assert_theme(text)["row_relevant"] is expected


@pytest.mark.parametrize(
    "term", ["COTAS + MULHERES", "COTAS + GÊNERO", "POLÍTICA + MULHERES", "POLÍTICA + MULHER"]
)
def test_explicit_conjunction(term):
    RelevanceTerm.objects.create(term=term, mode="combined")
    left, right = term.split(" + ")
    assert not assert_theme(left)["row_relevant"]
    assert not assert_theme(right)["row_relevant"]
    assert assert_theme(f"{right}\n legislação sobre {left}")["temas"] == [term]
    assert assert_theme(left, right)["row_relevant"]
    assert not assert_theme(f"{left} {right}XYZ")["row_relevant"]


def test_accents_preserved_but_unicode_normalized():
    import unicodedata

    RelevanceTerm.objects.create(term="GÊNERO")
    assert assert_theme(unicodedata.normalize("NFD", "gênero"))["row_relevant"]
    assert not assert_theme("genero")["row_relevant"]


def test_vocabulary_migration_activates_exact_requested_set():
    from importlib import import_module
    from types import SimpleNamespace

    from django.apps import apps
    from django.db import connection

    from apps.ingestion.relevance_defaults import DEFAULT_COMBINED, DEFAULT_STANDALONE

    RelevanceTerm.objects.create(term="TERMO ANTIGO")
    RelevanceTerm.objects.create(term="TRABALHO", mode="combined")
    RelevanceTerm.objects.create(term="ABORTO", is_active=False)
    migration = import_module("apps.ingestion.migrations.0005_update_relevance_vocabulary")
    for _ in range(2):
        migration.update_terms(apps, SimpleNamespace(connection=connection))
        active = set(RelevanceTerm.objects.filter(is_active=True).values_list("term", "mode"))
        expected = {(term, "standalone") for term in DEFAULT_STANDALONE}
        expected |= {(term, "combined") for term in DEFAULT_COMBINED}
        assert active == expected
        assert len(active) == 302
    assert not RelevanceTerm.objects.get(term="TERMO ANTIGO").is_active
    assert not RelevanceTerm.objects.get(term="TRABALHO", mode="combined").is_active
    assert assert_theme("TRABALHO")["row_relevant"]
