from django.db import transaction
from django.db.models.signals import post_delete, post_save, pre_save
from django.dispatch import receiver


def _enqueue(proposition_id: int):
    from apps.subscriptions.tasks import match_and_notify

    # on_commit: a ingestão grava proposição, autores e temas na mesma
    # transação — enfileirar antes do commit faz o worker ler um documento pela
    # metade (ou nada, se a transação falhar).
    transaction.on_commit(lambda: match_and_notify.delay(proposition_id))


@receiver(pre_save, sender="propositions.Proposition")
def remember_approval_transition(sender, instance, **kwargs):
    """Marca a transição pendente para aprovada, antes de a linha ser gravada."""
    instance._became_approved = False
    update_fields = kwargs.get("update_fields")
    if instance._state.adding or (update_fields and "is_approved" not in update_fields):
        return

    previous_is_approved = (
        sender.objects.filter(pk=instance.pk).values_list("is_approved", flat=True).first()
    )
    instance._became_approved = previous_is_approved is False and instance.is_approved


@receiver(post_save, sender="propositions.Proposition")
def enqueue_match_on_proposition(sender, instance, created, **kwargs):
    """Dispara alertas somente quando uma proposição se torna pública."""
    if (created and instance.is_approved) or getattr(instance, "_became_approved", False):
        _enqueue(instance.pk)
    # Aprovação, tipo e metadados da proposição podem mudar o conjunto público.
    from .activity import invalidate_activity_cache

    invalidate_activity_cache([instance])


@receiver(post_save, sender="propositions.PropositionAnnotation")
def enqueue_match_on_annotation(sender, instance, **kwargs):
    """A categoria ("Categorias 2026") é a anotação humana, e chega dias depois
    da coleta. Sem este gatilho, alerta por categoria nunca dispararia."""
    _enqueue(instance.proposition_id)
    from .activity import invalidate_activity_cache

    invalidate_activity_cache([instance.proposition])


@receiver(post_save, sender="propositions.PropositionAnalysis")
def invalidate_activity_after_quiteria_analysis(sender, instance, **kwargs):
    """A conclusão da QuitérIA altera categoria, avaliação e avaliadora públicas."""
    from .activity import invalidate_activity_cache

    invalidate_activity_cache([instance.proposition])


@receiver(post_save, sender="legislatures.Parliamentarian")
def invalidate_activity_after_author_profile(sender, instance, **kwargs):
    from .activity import invalidate_activity_cache
    from .models import Proposition

    invalidate_activity_cache(Proposition.objects.filter(authors__parliamentarian=instance).distinct())


@receiver(post_save, sender="propositions.PropositionAuthor")
@receiver(post_delete, sender="propositions.PropositionAuthor")
def invalidate_activity_after_authorship(sender, instance, **kwargs):
    from .activity import invalidate_activity_cache

    invalidate_activity_cache([instance.proposition])
