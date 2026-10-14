from celery import shared_task
from django.conf import settings
from django.core.cache import cache

from .services import sync
from .targets import build_targets

LOCK_TIMEOUT_SECONDS = 5 * 60


def _pending_key(parliamentarian_id: int) -> str:
    return f"og:pending:{parliamentarian_id}"


def enqueue_og_render(parliamentarian_ids) -> None:
    """Agenda uma renderização por parlamentar, agrupando rajadas de eventos.

    Durante a ingestão, várias proposições da mesma autora são classificadas
    em minutos; só o primeiro evento da janela agenda o job, que lê o estado
    do banco quando roda.
    """
    if not settings.OG_S3_BUCKET:
        return
    delay = settings.OG_RENDER_DELAY_SECONDS
    for parliamentarian_id in {pid for pid in parliamentarian_ids if pid}:
        if cache.add(_pending_key(parliamentarian_id), 1, timeout=delay + LOCK_TIMEOUT_SECONDS):
            render_parliamentarian_og.apply_async(args=[parliamentarian_id], countdown=delay)


@shared_task
def render_parliamentarian_og(parliamentarian_id: int, force: bool = False) -> str:
    cache.delete(_pending_key(parliamentarian_id))
    lock = f"og:lock:{parliamentarian_id}"
    if not cache.add(lock, 1, timeout=LOCK_TIMEOUT_SECONDS):
        # Outro job está publicando esta parlamentar; reagenda para pegar o estado final.
        enqueue_og_render([parliamentarian_id])
        return "locked"
    try:
        target = build_targets({parliamentarian_id}).get(parliamentarian_id)
        return sync(parliamentarian_id, target, force=force)
    finally:
        cache.delete(lock)
