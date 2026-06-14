import pytest

from apps.ingestion.models import RelevanceTerm
from apps.ingestion.theme_assert import assert_theme

pytestmark = pytest.mark.django_db


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
