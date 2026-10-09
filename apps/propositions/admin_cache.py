"""Invalidação do cache público a partir de edições no admin."""

from django.db import transaction


class ActivityCacheAdminMixin:
    """Expira as respostas `activity:*` depois de salvar ou excluir no admin.

    Usado em models que aparecem no painel público, mas que a ingestão também
    grava em lote (temas, partidos, autores). Por isso a invalidação fica no
    admin e não em signals: a coleta já invalida o cache ao fim de cada lote.
    """

    def _invalidate_activity_cache(self):
        from .activity import invalidate_activity_cache

        transaction.on_commit(invalidate_activity_cache)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        self._invalidate_activity_cache()

    def delete_model(self, request, obj):
        super().delete_model(request, obj)
        self._invalidate_activity_cache()

    def delete_queryset(self, request, queryset):
        super().delete_queryset(request, queryset)
        self._invalidate_activity_cache()
