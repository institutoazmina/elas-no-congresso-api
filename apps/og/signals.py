"""Eventos que podem mudar o que vai desenhado na imagem de uma parlamentar.

Nome e foto (perfil), partido/UF (mandato) e os totais favorável/desfavorável
(proposição, autoria, anotação humana e classificação da QuitérIA). O job
compara a impressão digital antes de renderizar, então evento sem mudança
visível não publica nada.
"""

from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver


def _enqueue(parliamentarian_ids) -> None:
    from .tasks import enqueue_og_render

    ids = list(parliamentarian_ids)
    transaction.on_commit(lambda: enqueue_og_render(ids))


def _enqueue_authors(proposition_id: int) -> None:
    from django.conf import settings

    if not settings.OG_S3_BUCKET:
        return

    def resolve():
        from apps.propositions.models import PropositionAuthor

        from .tasks import enqueue_og_render

        # Resolvido após o commit: a ingestão recria as autorias depois de
        # gravar a proposição, na mesma transação.
        enqueue_og_render(
            PropositionAuthor.objects.filter(
                proposition_id=proposition_id, parliamentarian__isnull=False
            ).values_list("parliamentarian_id", flat=True)
        )

    transaction.on_commit(resolve)


@receiver(post_save, sender="propositions.Proposition")
def og_on_proposition(sender, instance, **kwargs):
    _enqueue_authors(instance.pk)


@receiver(post_save, sender="propositions.PropositionAnnotation")
@receiver(post_delete, sender="propositions.PropositionAnnotation")
@receiver(post_save, sender="propositions.PropositionAnalysis")
def og_on_assessment(sender, instance, **kwargs):
    _enqueue_authors(instance.proposition_id)


@receiver(post_save, sender="propositions.PropositionAuthor")
@receiver(post_delete, sender="propositions.PropositionAuthor")
def og_on_authorship(sender, instance, **kwargs):
    _enqueue([instance.parliamentarian_id])


@receiver(post_save, sender="legislatures.Parliamentarian")
def og_on_profile(sender, instance, **kwargs):
    _enqueue([instance.pk])


@receiver(post_save, sender="legislatures.ParliamentarianTerm")
def og_on_term(sender, instance, **kwargs):
    _enqueue([instance.parliamentarian_id])
