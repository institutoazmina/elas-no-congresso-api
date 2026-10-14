"""Sincronização idempotente da imagem de uma parlamentar com o estado do banco."""

import logging

import httpx
from django.utils import timezone

from . import storage
from .models import ParliamentarianOgImage
from .renderer import OgData, render
from .targets import OgTarget

logger = logging.getLogger(__name__)

PHOTO_TIMEOUT_SECONDS = 10


def _load_photo(url: str | None) -> bytes | None:
    if not url:
        return None
    try:
        response = httpx.get(url, timeout=PHOTO_TIMEOUT_SECONDS, follow_redirects=True)
        response.raise_for_status()
        return response.content
    except httpx.HTTPError as exc:
        logger.warning("OG: foto indisponível %s (%s)", url, exc)
        return None


def render_target(target: OgTarget) -> tuple[bytes, bool]:
    """PNG da imagem e se a foto esperada foi carregada."""
    photo = _load_photo(target.photo_url)
    png = render(
        OgData(
            name=target.name,
            affiliation=target.affiliation,
            favorable=target.favorable,
            unfavorable=target.unfavorable,
            portrait=photo,
        )
    )
    return png, photo is not None or target.photo_url is None


def sync(parliamentarian_id: int, target: OgTarget | None, *, force: bool = False) -> str:
    """Publica, mantém ou remove a imagem. Devolve o que foi feito."""
    record = ParliamentarianOgImage.objects.filter(parliamentarian_id=parliamentarian_id).first()

    if target is None:
        if record is None:
            return "skipped"
        storage.delete(record.s3_key)
        record.delete()
        return "deleted"

    if record and not force and record.fingerprint == target.fingerprint:
        return "unchanged"

    try:
        png, photo_loaded = render_target(target)
        storage.upload(target.s3_key, png)
    except Exception as exc:
        logger.exception("OG: falha ao publicar a parlamentar %s", parliamentarian_id)
        ParliamentarianOgImage.objects.filter(parliamentarian_id=parliamentarian_id).update(
            last_error=f"{type(exc).__name__}: {exc}"
        )
        return "failed"

    if record and record.s3_key != target.s3_key:
        # O slug mudou com o nome: a imagem antiga não tem mais página.
        storage.delete(record.s3_key)
    ParliamentarianOgImage.objects.update_or_create(
        parliamentarian_id=parliamentarian_id,
        defaults={
            "fingerprint": target.fingerprint if photo_loaded else "",
            "s3_key": target.s3_key,
            "rendered_at": timezone.now(),
            "last_error": "" if photo_loaded else "Foto indisponível; renderizada com iniciais",
        },
    )
    return "rendered"
