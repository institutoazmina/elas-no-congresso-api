import uuid
from urllib.parse import urlparse

from django.core.exceptions import ValidationError
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
        # Duas linhas no máximo, no celular e ao lado da ilustração no computador.
        max_length=24,
        default=default,
        help_text="Até 24 caracteres, no máximo duas linhas.",
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

    @classmethod
    def default_images(cls):
        return [("hero_image", cls.DEFAULT_HERO_IMAGE, cls.HERO_IMAGE)]


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


class ActivityPage(HeroPage):
    DEFAULT_HERO_IMAGE = "activity-hero.png"

    title = title_field("Atividade Legislativa")
    subtitle = subtitle_field(
        "Use filtros e explore as movimentações do Legislativo sensíveis a gênero, "
        "atualizadas diariamente pela nossa robô que monitora o Congresso."
    )
    hero_image = hero_image_field("atividade-legislativa")

    class Meta:
        verbose_name = "Atividade legislativa"
        verbose_name_plural = "Atividade legislativa"
        db_table = "cms_activity_page"

    def __str__(self):
        return "Página de atividade legislativa"


class FeministAIPage(CmsPage):
    """Conteúdo editorial da página QuitérIA, com layout fixo no site."""

    HERO_IMAGE = ImageSpec(743, 1349)
    FLOW_DESKTOP_IMAGE = ImageSpec(820, 574)
    FLOW_MOBILE_IMAGE = ImageSpec(524, 574)

    seo_title = models.CharField("Título para busca", max_length=120)
    seo_description = models.CharField("Descrição para busca", max_length=200)

    hero_title_prefix = models.CharField("Início do título", max_length=30)
    hero_title_emphasis = models.CharField("Destaque do título", max_length=40)
    hero_description = models.TextField("Texto do topo", max_length=600)
    hero_image_width = models.PositiveIntegerField(default=743, editable=False)
    hero_image_height = models.PositiveIntegerField(default=1349, editable=False)
    hero_image = models.ImageField(
        "Ilustração de Maria Quitéria",
        upload_to="cms/ia-feminista/",
        storage=CmsStorage(),
        width_field="hero_image_width",
        height_field="hero_image_height",
        default="cms/ia-feminista/hero.webp",
        help_text="PNG, JPEG ou WebP com proporção de 743×1349 px, até 5 MB.",
    )
    hero_image_alt = models.CharField("Descrição da ilustração", max_length=160)

    differential_heading = models.CharField("Título da seção", max_length=100)
    differential_paragraph_1 = models.TextField("Parágrafo 1", max_length=1000)
    differential_paragraph_2 = models.TextField("Parágrafo 2", max_length=1000)
    differential_paragraph_3 = models.TextField("Parágrafo 3", max_length=1000)
    flow_heading = models.CharField("Título do fluxograma", max_length=100)
    flow_image_alt = models.CharField("Descrição do fluxograma", max_length=160)
    flow_desktop_width = models.PositiveIntegerField(default=820, editable=False)
    flow_desktop_height = models.PositiveIntegerField(default=574, editable=False)
    flow_desktop_image = models.ImageField(
        "Fluxograma para computador",
        upload_to="cms/ia-feminista/",
        storage=CmsStorage(),
        width_field="flow_desktop_width",
        height_field="flow_desktop_height",
        default="cms/ia-feminista/flow-desktop.webp",
        help_text="PNG, JPEG ou WebP com proporção de 820×574 px, até 5 MB.",
    )
    flow_mobile_width = models.PositiveIntegerField(default=524, editable=False)
    flow_mobile_height = models.PositiveIntegerField(default=574, editable=False)
    flow_mobile_image = models.ImageField(
        "Fluxograma para celular",
        upload_to="cms/ia-feminista/",
        storage=CmsStorage(),
        width_field="flow_mobile_width",
        height_field="flow_mobile_height",
        default="cms/ia-feminista/flow-mobile.webp",
        help_text="PNG, JPEG ou WebP com proporção de 524×574 px, até 5 MB.",
    )
    architecture_heading = models.CharField("Título dos cartões", max_length=100)
    architecture_card_1_title = models.CharField("Cartão 1: título", max_length=100)
    architecture_card_1_text = models.TextField("Cartão 1: texto", max_length=500)
    architecture_card_1_highlight = models.CharField("Cartão 1: destaque", max_length=80)
    architecture_card_1_note = models.CharField("Cartão 1: complemento", max_length=120)
    architecture_card_2_title = models.CharField("Cartão 2: título", max_length=100)
    architecture_card_2_text = models.TextField("Cartão 2: texto", max_length=500)

    feminism_heading = models.CharField("Título da seção", max_length=100)
    feminism_paragraph_1_before_link = models.TextField(
        "Parágrafo 1: antes do link", max_length=500
    )
    feminism_paragraph_1_link_text = models.CharField("Parágrafo 1: texto do link", max_length=160)
    feminism_paragraph_1_link_url = models.URLField("Parágrafo 1: endereço do link")
    feminism_paragraph_1_after_link = models.TextField(
        "Parágrafo 1: depois do link", max_length=300
    )
    feminism_paragraph_2 = models.TextField("Parágrafo 2", max_length=1000)
    feminism_paragraph_3_before_highlight = models.TextField(
        "Parágrafo 3: antes do destaque", max_length=300
    )
    feminism_paragraph_3_highlight = models.CharField("Parágrafo 3: destaque", max_length=160)
    feminism_paragraph_3_after_highlight = models.TextField(
        "Parágrafo 3: depois do destaque", max_length=500
    )
    categories_heading = models.CharField("Título da tabela", max_length=100)
    categories_name_column = models.CharField("Coluna: categoria", max_length=80)
    categories_concept_column = models.CharField("Coluna: conceito", max_length=80)

    governance_heading = models.CharField("Título da seção", max_length=100)
    governance_paragraph_1_before_link = models.TextField(
        "Parágrafo 1: antes do link", max_length=1000
    )
    governance_paragraph_1_link_text = models.CharField(
        "Parágrafo 1: texto do link", max_length=160
    )
    governance_paragraph_1_link_url = models.URLField("Parágrafo 1: endereço do link")
    governance_paragraph_1_after_link = models.TextField(
        "Parágrafo 1: depois do link", max_length=500
    )
    governance_paragraph_2 = models.TextField("Parágrafo 2", max_length=1500)
    supervision_heading = models.CharField("Título dos comitês", max_length=100)
    supervision_card_1_title = models.CharField("Comitê 1: título", max_length=100)
    supervision_card_1_text = models.TextField("Comitê 1: texto", max_length=500)
    supervision_card_1_note = models.CharField("Comitê 1: período", max_length=160)
    supervision_card_2_title = models.CharField("Comitê 2: título", max_length=100)
    supervision_card_2_text = models.TextField("Comitê 2: texto", max_length=500)
    supervision_card_2_note = models.CharField("Comitê 2: período", max_length=160)
    limitations_heading = models.CharField("Título das limitações", max_length=100)
    limitations_intro = models.TextField("Introdução das limitações", max_length=500)

    performance_heading = models.CharField("Título da seção", max_length=100)
    evaluation_caption = models.CharField("Legenda da comparação", max_length=160)
    evaluation_metric_help_url = models.URLField("Link de ajuda: métricas")
    evaluation_metric_column = models.CharField("Coluna: métrica", max_length=80)
    evaluation_previous_column = models.CharField("Coluna da versão anterior", max_length=80)
    evaluation_current_column = models.CharField("Coluna da versão atual", max_length=80)
    evaluation_partition_caption = models.CharField("Legenda da partição", max_length=100)
    evaluation_partition_name_column = models.CharField("Coluna: partição", max_length=80)
    evaluation_partition_accuracy_column = models.CharField("Coluna: acurácia", max_length=80)
    evaluation_partition_percent_column = models.CharField("Coluna: percentual", max_length=80)
    evaluation_partition_count_column = models.CharField("Coluna: quantidade", max_length=80)
    thematic_caption = models.CharField("Legenda da categorização", max_length=160)
    thematic_partition_caption = models.CharField("Legenda da partição temática", max_length=100)
    thematic_partition_name_column = models.CharField("Coluna: base", max_length=80)
    thematic_partition_training_column = models.CharField("Coluna: treino", max_length=80)
    thematic_partition_validation_column = models.CharField("Coluna: validação", max_length=80)
    thematic_partition_test_column = models.CharField("Coluna: teste", max_length=80)

    open_data_heading = models.CharField("Título da seção", max_length=100)
    open_data_intro = models.TextField("Introdução", max_length=500)

    class Meta:
        verbose_name = "IA Feminista"
        verbose_name_plural = "IA Feminista"
        db_table = "cms_feminist_ai_page"

    def __str__(self):
        return "Página de IA Feminista"

    @classmethod
    def default_images(cls):
        return [
            ("hero_image", "feminist-ai-hero.png", cls.HERO_IMAGE),
            ("flow_desktop_image", "feminist-ai-flow-desktop.png", cls.FLOW_DESKTOP_IMAGE),
            ("flow_mobile_image", "feminist-ai-flow-mobile.png", cls.FLOW_MOBILE_IMAGE),
        ]


class FeministAIOrderedItem(models.Model):
    page = models.ForeignKey(FeministAIPage, on_delete=models.CASCADE)
    position = models.PositiveSmallIntegerField("Ordem")

    class Meta:
        abstract = True
        ordering = ["position", "pk"]


class FeministAICategory(FeministAIOrderedItem):
    name = models.CharField("Categoria", max_length=160)
    concept = models.TextField("Conceito", max_length=1500)

    class Meta(FeministAIOrderedItem.Meta):
        verbose_name = "Categoria temática"
        verbose_name_plural = "Categorias temáticas"

    def __str__(self):
        return self.name


class FeministAILimitation(FeministAIOrderedItem):
    text = models.TextField("Texto", max_length=500)

    class Meta(FeministAIOrderedItem.Meta):
        verbose_name = "Limitação"
        verbose_name_plural = "Limitações"

    def __str__(self):
        return self.text[:80]


class FeministAIEvaluationMetric(FeministAIOrderedItem):
    label = models.CharField("Métrica", max_length=100)
    url = models.URLField("Link explicativo", blank=True)
    previous = models.CharField("Versão anterior", max_length=50)
    current = models.CharField("Versão atual", max_length=50)
    trend = models.CharField(
        "Tendência",
        max_length=7,
        choices=[("up", "Melhorou"), ("down", "Piorou"), ("neutral", "Sem comparação")],
    )

    class Meta(FeministAIOrderedItem.Meta):
        verbose_name = "Métrica de desfavorabilidade"
        verbose_name_plural = "Métricas de desfavorabilidade"

    def __str__(self):
        return self.label


class FeministAIEvaluationPartition(FeministAIOrderedItem):
    label = models.CharField("Partição", max_length=80)
    accuracy = models.CharField("Acurácia", max_length=50)
    percentage = models.CharField("Percentual da base", max_length=50)
    count = models.CharField("Quantidade absoluta", max_length=50)

    class Meta(FeministAIOrderedItem.Meta):
        verbose_name = "Partição de desfavorabilidade"
        verbose_name_plural = "Partições de desfavorabilidade"

    def __str__(self):
        return self.label


class FeministAIThematicMetric(FeministAIOrderedItem):
    label = models.CharField("Métrica", max_length=160)
    value = models.CharField("Valor", max_length=50)

    class Meta(FeministAIOrderedItem.Meta):
        verbose_name = "Métrica de categorização temática"
        verbose_name_plural = "Métricas de categorização temática"

    def __str__(self):
        return self.label


class FeministAIThematicPartition(FeministAIOrderedItem):
    label = models.CharField("Base", max_length=160)
    training = models.CharField("Treino", max_length=50)
    validation = models.CharField("Validação", max_length=50)
    test = models.CharField("Teste", max_length=50)

    class Meta(FeministAIOrderedItem.Meta):
        verbose_name = "Partição temática"
        verbose_name_plural = "Partições temáticas"

    def __str__(self):
        return self.label


class FeministAIOpenLink(FeministAIOrderedItem):
    label = models.CharField("Texto do link", max_length=160)
    url = models.URLField("Endereço")

    class Meta(FeministAIOrderedItem.Meta):
        verbose_name = "Link de código e dados"
        verbose_name_plural = "Links de código e dados"

    def __str__(self):
        return self.label


class AboutPage(CmsPage):
    """Conteúdo fixo da página Sobre e raiz da linha do tempo editável."""

    HERO_IMAGE = ImageSpec(1080, 1350)
    seo_title = models.CharField("Título para buscas", max_length=160)
    seo_description = models.CharField("Descrição para buscas", max_length=300)
    hero_image_width = models.PositiveIntegerField(default=1080, editable=False)
    hero_image_height = models.PositiveIntegerField(default=1350, editable=False)
    hero_image = hero_image_field("sobre")
    timeline_note_link_text = models.CharField(
        "Nota da linha do tempo: texto do link", max_length=200
    )
    timeline_note_link_url = models.URLField("Nota da linha do tempo: endereço")
    timeline_note_after_link = models.CharField(
        "Nota da linha do tempo: depois do link", max_length=200
    )

    class Meta:
        verbose_name = "Sobre: página e linha do tempo"
        verbose_name_plural = "Sobre: página e linha do tempo"
        db_table = "cms_about_page"

    def __str__(self):
        return "Página Sobre"

    @classmethod
    def default_images(cls):
        return [("hero_image", "about-hero.png", cls.HERO_IMAGE)]


class AboutCopy(models.Model):
    """Trecho editável de texto ou endereço; o layout e a formatação ficam no Astro."""

    page = models.ForeignKey(AboutPage, on_delete=models.CASCADE, related_name="copy")
    key = models.CharField("Identificador", max_length=20, unique=True, editable=False)
    section = models.CharField("Seção", max_length=80, db_index=True, editable=False)
    label = models.CharField("Identificação do trecho", max_length=110, editable=False)
    value = models.TextField("Conteúdo", max_length=4000)
    position = models.PositiveSmallIntegerField("Ordem", editable=False)

    class Meta:
        ordering = ["position"]
        verbose_name = "Sobre: texto e link"
        verbose_name_plural = "Sobre: textos e links"
        db_table = "cms_about_copy"

    def clean(self):
        if self.label.startswith("Link URL"):
            parsed = urlparse(self.value)
            relative = self.value.startswith("/") and not self.value.startswith("//")
            absolute = parsed.scheme in {"http", "https"} and bool(parsed.netloc)
            if not (relative or absolute):
                raise ValidationError(
                    {"value": "Use um endereço https:// ou um caminho do site (/...)."}
                )

    def __str__(self):
        return f"{self.section}: {self.label}"


class AboutTimelineEvent(models.Model):
    page = models.ForeignKey(AboutPage, on_delete=models.CASCADE, related_name="timeline")
    position = models.PositiveSmallIntegerField("Ordem")
    date_prefix = models.CharField("Período: antes do ano", max_length=60)
    year = models.CharField("Ano", max_length=40)
    description_before_link = models.TextField("Descrição", max_length=1500)
    link_text = models.CharField("Texto do link", max_length=160, blank=True)
    link_url = models.URLField("Endereço do link", blank=True)
    description_after_link = models.TextField("Descrição após o link", max_length=1500, blank=True)
    tag = models.CharField("Etiqueta", max_length=60)

    class Meta:
        ordering = ["position", "pk"]
        verbose_name = "Marco da linha do tempo"
        verbose_name_plural = "Marcos da linha do tempo"
        db_table = "cms_about_timeline_event"

    def __str__(self):
        return f"{self.year}: {self.tag}"


class AboutChallenge(models.Model):
    page = models.ForeignKey(AboutPage, on_delete=models.CASCADE, related_name="challenges")
    position = models.PositiveSmallIntegerField("Ordem")
    title = models.CharField("Título", max_length=100)
    text = models.TextField("Descrição", max_length=1500)

    class Meta:
        ordering = ["position", "pk"]
        verbose_name = "Desafio"
        verbose_name_plural = "Desafios"
        db_table = "cms_about_challenge"

    def __str__(self):
        return self.title


def partner_logo_path(instance, filename):
    """URL estável quando a equipe substitui o logo de uma organização."""
    if instance.pk:
        previous = (
            type(instance)
            .objects.filter(pk=instance.pk)
            .values_list("logo_image", flat=True)
            .first()
        )
        if previous:
            return previous
    return f"cms/sobre/partners/{uuid.uuid4().hex}.webp"


class AboutPartner(models.Model):
    page = models.ForeignKey(AboutPage, on_delete=models.CASCADE, related_name="partners")
    position = models.PositiveSmallIntegerField("Ordem")
    name = models.CharField("Organização", max_length=160)
    asset_key = models.CharField("Logo original", max_length=60, blank=True, editable=False)
    logo_image = models.ImageField(
        "Novo logo",
        blank=True,
        upload_to=partner_logo_path,
        storage=CmsStorage(),
        help_text="PNG, JPEG ou WebP com até 5 MB. O logo se ajusta ao espaço disponível.",
    )

    class Meta:
        ordering = ["position", "pk"]
        verbose_name = "Organização parceira"
        verbose_name_plural = "Organizações parceiras"
        db_table = "cms_about_partner"

    def clean(self):
        if not self.asset_key and not self.logo_image:
            raise ValidationError({"logo_image": "Envie o logo da nova organização."})

    def __str__(self):
        return self.name
