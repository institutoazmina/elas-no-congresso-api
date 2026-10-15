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


def title_field(default: str):
    return models.CharField(
        verbose_name="Título",
        # No celular o título não quebra linha: ~15 maiúsculas cabem em 375 px.
        max_length=14,
        default=default,
        help_text="Até 14 caracteres. No celular o título fica numa linha só.",
    )


def subtitle_field(default: str):
    return models.CharField(
        verbose_name="Subtítulo",
        max_length=160,
        default=default,
        help_text="Até 160 caracteres, cerca de três linhas no computador.",
    )


def hero_image_field(folder: str):
    # Obrigatória: ``cms_publish_defaults`` publica a ilustração original neste
    # caminho, e cada envio a substitui no mesmo arquivo.
    return models.ImageField(
        verbose_name="Ilustração",
        upload_to=f"cms/{folder}/",
        storage=CmsStorage(),
        width_field="hero_image_width",
        height_field="hero_image_height",
        default=f"cms/{folder}/hero.webp",
        help_text=(
            f"Para substituir, envie PNG, JPEG ou WebP com a proporção de "
            f"{HeroPage.HERO_IMAGE.label} (4:5), até 5 MB. Some no celular."
        ),
    )


class HeroPage(CmsPage):
    """Página com o topo padrão do site: título, subtítulo e ilustração 4:5.

    Cada página declara os campos com seus valores padrão e o arquivo original
    da ilustração em ``apps/cms/defaults/``.
    """

    HERO_IMAGE = ImageSpec(1080, 1350)
    DEFAULT_HERO_IMAGE: str

    hero_image_width = models.PositiveIntegerField(default=HERO_IMAGE.width, editable=False)
    hero_image_height = models.PositiveIntegerField(default=HERO_IMAGE.height, editable=False)

    class Meta:
        abstract = True


class AlertsPage(HeroPage):
    DEFAULT_HERO_IMAGE = "alerts-hero.png"

    title = title_field("Alertas")
    subtitle = subtitle_field("Acompanhe as movimentações do Legislativo no Radar do Congresso")
    hero_image = hero_image_field("alertas")

    class Meta:
        verbose_name = "Alertas"
        verbose_name_plural = "Alertas"
        db_table = "cms_alerts_page"

    def __str__(self):
        return "Página de alertas"


class ReportsPage(HeroPage):
    DEFAULT_HERO_IMAGE = "reports-hero.png"

    title = title_field("Reportagens")
    subtitle = subtitle_field("Veja as histórias que os dados do Congresso nos contam.")
    hero_image = hero_image_field("reportagens")

    class Meta:
        verbose_name = "Reportagens"
        verbose_name_plural = "Reportagens"
        db_table = "cms_reports_page"

    def __str__(self):
        return "Página de reportagens"
