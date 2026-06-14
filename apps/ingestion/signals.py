from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver


@receiver([post_save, post_delete], sender="ingestion.RelevanceTerm")
def _invalidate_theme_cache(sender, **kwargs):
    """Limpa o cache de termos do theme_assert quando a operação edita no admin."""
    from .theme_assert import invalidate_cache

    invalidate_cache()
