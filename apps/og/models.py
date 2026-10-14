from django.db import models

from apps.legislatures.models import Parliamentarian


class ParliamentarianOgImage(models.Model):
    """Última imagem de compartilhamento publicada para uma parlamentar."""

    parliamentarian = models.OneToOneField(
        Parliamentarian,
        verbose_name="Parlamentar",
        on_delete=models.CASCADE,
        related_name="og_image",
    )
    # Vazio quando a foto falhou: o próximo evento tenta renderizar de novo.
    fingerprint = models.CharField(verbose_name="Impressão digital", max_length=64, blank=True)
    s3_key = models.TextField(verbose_name="Chave no S3")
    rendered_at = models.DateTimeField(verbose_name="Renderizada em", null=True, blank=True)
    last_error = models.TextField(verbose_name="Último erro", blank=True)

    class Meta:
        verbose_name = "Imagem de compartilhamento"
        verbose_name_plural = "Imagens de compartilhamento"
        db_table = "parliamentarian_og_images"

    def __str__(self):
        return self.s3_key
