from django.db.models.signals import post_save
from django.dispatch import receiver


@receiver(post_save, sender="propositions.Proposition")
def enqueue_match_on_save(sender, instance, created, **kwargs):
    if created:
        from apps.subscriptions.tasks import match_and_notify
        match_and_notify.delay(instance.pk)
