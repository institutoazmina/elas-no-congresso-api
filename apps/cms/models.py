from django.db import models

from .images import ImageSpec
from .storage import CmsStorage


class CmsPage(models.Model):
    """Página do site com um único registro editável.

    Só o texto e as imagens vêm daqui; o layout continua no código do site,
    por isso cada campo tem o limite que o layout comporta.
    """

    SINGLETON_PK = 1

    updated_at = models.DateTimeField(verbose_name="Atualizado em", auto_now=True)

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        self.pk = self.SINGLETON_PK
        super().save(*args, **kwargs)

    @classmethod
    def load(cls):
        page, _ = cls.objects.get_or_create(pk=cls.SINGLETON_PK)
        return page

    @classmethod
    def current(cls):
        """Registro salvo ou, antes da primeira edição, os valores padrão sem gravar."""
        return cls.objects.filter(pk=cls.SINGLETON_PK).first() or cls(pk=cls.SINGLETON_PK)


class AlertsPage(CmsPage):
    HERO_IMAGE = ImageSpec(1080, 1350)

    title = models.CharField(
        verbose_name="Título",
        # No celular o título não quebra linha: ~15 maiúsculas cabem em 375 px.
        max_length=14,
        default="Alertas",
        help_text="Até 14 caracteres. No celular o título fica numa linha só.",
    )
    subtitle = models.CharField(
        verbose_name="Subtítulo",
        max_length=160,
        default="Acompanhe as movimentações do Legislativo no Radar do Congresso",
        help_text="Até 160 caracteres, cerca de três linhas no computador.",
    )
    # Obrigatória: ``cms_publish_defaults`` publica a ilustração original neste
    # caminho, e cada envio a substitui no mesmo arquivo.
    hero_image = models.ImageField(
        verbose_name="Ilustração",
        upload_to="cms/alertas/",
        storage=CmsStorage(),
        width_field="hero_image_width",
        height_field="hero_image_height",
        default="cms/alertas/hero.webp",
        help_text=(
            f"Para substituir, envie PNG, JPEG ou WebP com a proporção de {HERO_IMAGE.label} "
            "(4:5), até 5 MB. Some no celular."
        ),
    )
    hero_image_width = models.PositiveIntegerField(default=HERO_IMAGE.width, editable=False)
    hero_image_height = models.PositiveIntegerField(default=HERO_IMAGE.height, editable=False)

    class Meta:
        verbose_name = "Alertas"
        verbose_name_plural = "Alertas"
        db_table = "cms_alerts_page"

    def __str__(self):
        return "Página de alertas"
