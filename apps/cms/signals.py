from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import AboutCopy, CmsPage, HomeCopy


@receiver(post_save)
def deploy_on_cms_save(sender, **kwargs):
    if issubclass(sender, CmsPage) or sender in {AboutCopy, HomeCopy}:
        from .tasks import enqueue_site_deploy

        transaction.on_commit(enqueue_site_deploy)
