from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver


def _enqueue(proposition_id: int):
    from apps.subscriptions.tasks import match_and_notify

    # on_commit: a ingestão grava proposição, autores e temas na mesma
    # transação — enfileirar antes do commit faz o worker ler um documento pela
    # metade (ou nada, se a transação falhar).
    transaction.on_commit(lambda: match_and_notify.delay(proposition_id))


@receiver(post_save, sender="propositions.Proposition")
def enqueue_match_on_save(sender, instance, created, **kwargs):
    if created:
        _enqueue(instance.pk)


@receiver(post_save, sender="propositions.PropositionAnnotation")
def enqueue_match_on_annotation(sender, instance, **kwargs):
    """A categoria ("Categorias 2026") é a anotação humana, e chega dias depois
    da coleta. Sem este gatilho, alerta por categoria nunca dispararia."""
    _enqueue(instance.proposition_id)
