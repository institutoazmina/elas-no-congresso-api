from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.forms import modelform_factory
from django.shortcuts import redirect
from django.urls import reverse
from unfold.admin import ModelAdmin, TabularInline
from unfold.widgets import UnfoldAdminTextareaWidget

from .images import ImageSpec, normalize, normalize_logo, normalize_unconstrained
from .models import (
    AboutChallenge,
    AboutCopy,
    AboutPage,
    AboutPartner,
    AboutTimelineEvent,
    ActivityPage,
    AlertsPage,
    FeministAICategory,
    FeministAIEvaluationMetric,
    FeministAIEvaluationPartition,
    FeministAILimitation,
    FeministAIOpenLink,
    FeministAIPage,
    FeministAIThematicMetric,
    FeministAIThematicPartition,
    FooterAlertsPage,
    HeroPage,
    HomeCopy,
    HomePage,
    ReportsPage,
)


class CmsPageForm(forms.ModelForm):
    """Valida e regrava as imagens enviadas. Imagens são obrigatórias no model:
    sem a opção "limpar", só substituir."""

    def image_specs(self) -> dict[str, tuple[ImageSpec | None, str]]:
        """Campo -> (especificação, nome do arquivo no bucket)."""
        return {}

    def _get_validation_exclusions(self):
        excluded = super()._get_validation_exclusions()
        excluded.update(field for field in self.image_specs() if field not in self.cleaned_data)
        return excluded

    def clean(self):
        cleaned = super().clean()
        for field, (spec, stem) in self.image_specs().items():
            value = cleaned.get(field)
            if isinstance(value, UploadedFile):
                try:
                    cleaned[field] = (
                        normalize(value, spec, stem=stem)
                        if spec
                        else normalize_unconstrained(value, stem=stem)
                    )
                except ValidationError as exc:
                    self.add_error(field, exc)
            else:
                # Não reatribuir o arquivo atual: ImageField tentaria abri-lo
                # para recalcular dimensões, mesmo numa edição só de texto.
                cleaned.pop(field, None)
        return cleaned


class CmsPageAdmin(ModelAdmin):
    """Página de registro único: o menu abre direto o formulário de edição."""

    readonly_fields = ["updated_at"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        if not self.has_view_or_change_permission(request):
            raise PermissionDenied
        opts = self.model._meta
        page = self.model.load()
        return redirect(reverse(f"admin:{opts.app_label}_{opts.model_name}_change", args=[page.pk]))

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if settings.SITE_DEPLOY_GITHUB_TOKEN:
            messages.info(request, "O site será publicado com a alteração em alguns minutos.")


class HeroPageForm(CmsPageForm):
    def image_specs(self):
        return {"hero_image": (None, "hero")}


def hero_page_form(model: type[HeroPage]) -> type[forms.ModelForm]:
    return modelform_factory(
        model,
        form=HeroPageForm,
        fields=["title", "subtitle", "hero_image"],
        widgets={"subtitle": UnfoldAdminTextareaWidget(attrs={"rows": 3})},
    )


class HeroPageAdmin(CmsPageAdmin):
    fieldsets = [("Topo da página", {"fields": ["title", "subtitle", "hero_image", "updated_at"]})]


@admin.register(AlertsPage)
class AlertsPageAdmin(HeroPageAdmin):
    form = hero_page_form(AlertsPage)


@admin.register(ReportsPage)
class ReportsPageAdmin(HeroPageAdmin):
    form = hero_page_form(ReportsPage)


@admin.register(ActivityPage)
class ActivityPageAdmin(HeroPageAdmin):
    form = hero_page_form(ActivityPage)


class FeministAIPageForm(CmsPageForm):
    class Meta:
        model = FeministAIPage
        fields = "__all__"

    def image_specs(self):
        return {
            "hero_image": (None, "hero"),
            "flow_desktop_image": (FeministAIPage.FLOW_DESKTOP_IMAGE, "flow-desktop"),
            "flow_mobile_image": (FeministAIPage.FLOW_MOBILE_IMAGE, "flow-mobile"),
        }


class FeministAICategoryInline(TabularInline):
    model = FeministAICategory
    fields = ["position", "name", "concept"]
    extra = 0


class FeministAILimitationInline(TabularInline):
    model = FeministAILimitation
    fields = ["position", "text"]
    extra = 0


class FeministAIEvaluationMetricInline(TabularInline):
    model = FeministAIEvaluationMetric
    fields = ["position", "label", "url", "previous", "current", "trend"]
    extra = 0


class FeministAIEvaluationPartitionInline(TabularInline):
    model = FeministAIEvaluationPartition
    fields = ["position", "label", "accuracy", "percentage", "count"]
    extra = 0


class FeministAIThematicMetricInline(TabularInline):
    model = FeministAIThematicMetric
    fields = ["position", "label", "value"]
    extra = 0


class FeministAIThematicPartitionInline(TabularInline):
    model = FeministAIThematicPartition
    fields = ["position", "label", "training", "validation", "test"]
    extra = 0


class FeministAIOpenLinkInline(TabularInline):
    model = FeministAIOpenLink
    fields = ["position", "label", "url"]
    extra = 0


@admin.register(FeministAIPage)
class FeministAIPageAdmin(CmsPageAdmin):
    form = FeministAIPageForm
    fieldsets = [
        ("Busca e compartilhamento", {"fields": ["seo_title", "seo_description"]}),
        (
            "Quem foi Maria Quitéria?",
            {
                "fields": [
                    "hero_title_prefix",
                    "hero_title_emphasis",
                    "hero_description",
                    "hero_image",
                    "hero_image_alt",
                ]
            },
        ),
        (
            "Diferencial tecnológico",
            {
                "fields": [
                    "differential_heading",
                    "differential_paragraph_1",
                    "differential_paragraph_2",
                    "differential_paragraph_3",
                    "flow_heading",
                    "flow_desktop_image",
                    "flow_mobile_image",
                    "flow_image_alt",
                    "architecture_heading",
                    "architecture_card_1_title",
                    "architecture_card_1_text",
                    "architecture_card_1_highlight",
                    "architecture_card_1_note",
                    "architecture_card_2_title",
                    "architecture_card_2_text",
                ]
            },
        ),
        (
            "Feminismo de dados",
            {
                "fields": [
                    "feminism_heading",
                    "feminism_paragraph_1_before_link",
                    "feminism_paragraph_1_link_text",
                    "feminism_paragraph_1_link_url",
                    "feminism_paragraph_1_after_link",
                    "feminism_paragraph_2",
                    "feminism_paragraph_3_before_highlight",
                    "feminism_paragraph_3_highlight",
                    "feminism_paragraph_3_after_highlight",
                    "categories_heading",
                    "categories_name_column",
                    "categories_concept_column",
                ]
            },
        ),
        (
            "Governança e transparência",
            {
                "fields": [
                    "governance_heading",
                    "governance_paragraph_1_before_link",
                    "governance_paragraph_1_link_text",
                    "governance_paragraph_1_link_url",
                    "governance_paragraph_1_after_link",
                    "governance_paragraph_2",
                    "supervision_heading",
                    "supervision_card_1_title",
                    "supervision_card_1_text",
                    "supervision_card_1_note",
                    "supervision_card_2_title",
                    "supervision_card_2_text",
                    "supervision_card_2_note",
                    "limitations_heading",
                    "limitations_intro",
                ]
            },
        ),
        (
            "Desempenho do modelo",
            {
                "fields": [
                    "performance_heading",
                    "evaluation_caption",
                    "evaluation_metric_help_url",
                    "evaluation_metric_column",
                    "evaluation_previous_column",
                    "evaluation_current_column",
                    "evaluation_partition_caption",
                    "evaluation_partition_name_column",
                    "evaluation_partition_accuracy_column",
                    "evaluation_partition_percent_column",
                    "evaluation_partition_count_column",
                    "thematic_caption",
                    "thematic_partition_caption",
                    "thematic_partition_name_column",
                    "thematic_partition_training_column",
                    "thematic_partition_validation_column",
                    "thematic_partition_test_column",
                ]
            },
        ),
        ("Código e dados abertos", {"fields": ["open_data_heading", "open_data_intro"]}),
        ("Publicação", {"fields": ["updated_at"]}),
    ]
    inlines = [
        FeministAICategoryInline,
        FeministAILimitationInline,
        FeministAIEvaluationMetricInline,
        FeministAIEvaluationPartitionInline,
        FeministAIThematicMetricInline,
        FeministAIThematicPartitionInline,
        FeministAIOpenLinkInline,
    ]


class AboutPageForm(CmsPageForm):
    class Meta:
        model = AboutPage
        fields = "__all__"

    def image_specs(self):
        return {"hero_image": (None, "hero")}


class AboutTimelineInline(TabularInline):
    model = AboutTimelineEvent
    fields = [
        "position",
        "date_prefix",
        "year",
        "description_before_link",
        "link_text",
        "link_url",
        "description_after_link",
        "tag",
    ]
    extra = 0


class AboutChallengeInline(TabularInline):
    model = AboutChallenge
    fields = ["position", "title", "text"]
    extra = 0


class AboutPartnerForm(forms.ModelForm):
    class Meta:
        model = AboutPartner
        fields = "__all__"

    def clean_logo_image(self):
        value = self.cleaned_data.get("logo_image")
        if isinstance(value, UploadedFile):
            return normalize_logo(value)
        return value


class AboutPartnerInline(TabularInline):
    model = AboutPartner
    form = AboutPartnerForm
    fields = ["position", "name", "logo_image"]
    extra = 0


@admin.register(AboutPage)
class AboutPageAdmin(CmsPageAdmin):
    form = AboutPageForm
    fieldsets = [
        ("Busca e compartilhamento", {"fields": ["seo_title", "seo_description"]}),
        ("Ilustração da abertura", {"fields": ["hero_image"]}),
        (
            "Nota da linha do tempo",
            {
                "fields": [
                    "timeline_note_link_text",
                    "timeline_note_link_url",
                    "timeline_note_after_link",
                ]
            },
        ),
        ("Publicação", {"fields": ["updated_at"]}),
    ]
    inlines = [AboutTimelineInline, AboutChallengeInline, AboutPartnerInline]


class AboutCopyForm(forms.ModelForm):
    class Meta:
        model = AboutCopy
        fields = ["value"]
        widgets = {"value": forms.Textarea(attrs={"rows": 2, "cols": 70})}


@admin.register(AboutCopy)
class AboutCopyAdmin(ModelAdmin):
    """Trechos separados por seção, com rótulos legíveis e sem edição de HTML."""

    list_display = ["section", "label", "value"]
    form = AboutCopyForm
    list_editable = ["value"]
    list_filter = ["section"]
    search_fields = ["label", "value", "section"]
    readonly_fields = ["section", "label"]
    fields = ["section", "label", "value"]
    list_per_page = 30

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class HomePageForm(CmsPageForm):
    class Meta:
        model = HomePage
        fields = "__all__"

    def image_specs(self):
        return {
            "hero_image": (None, "hero"),
            "explore_image": (HomePage.EXPLORE_IMAGE, "explore"),
            "quiteria_image": (HomePage.QUITERIA_IMAGE, "quiteria"),
        }


@admin.register(HomePage)
class HomePageAdmin(CmsPageAdmin):
    form = HomePageForm
    fieldsets = [
        ("Abertura", {"fields": ["hero_image"]}),
        ("Explore", {"fields": ["explore_image"]}),
        ("QuitérIA", {"fields": ["quiteria_image"]}),
        ("Publicação", {"fields": ["updated_at"]}),
    ]


class HomeCopyForm(forms.ModelForm):
    class Meta:
        model = HomeCopy
        fields = ["value"]
        widgets = {"value": forms.Textarea(attrs={"rows": 2, "cols": 70})}


@admin.register(HomeCopy)
class HomeCopyAdmin(ModelAdmin):
    """Trechos agrupados por seção, sem exigir HTML da equipe editorial."""

    list_display = ["section", "label", "value"]
    form = HomeCopyForm
    list_editable = ["value"]
    list_filter = ["section"]
    search_fields = ["section", "label", "value"]
    readonly_fields = ["section", "label"]
    fields = ["section", "label", "value"]
    list_per_page = 50

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(FooterAlertsPage)
class FooterAlertsPageAdmin(CmsPageAdmin):
    fieldsets = [
        (
            "Receba nossos alertas em todo o site",
            {"fields": ["title", "text", "cta_text", "cta_url", "updated_at"]},
        ),
    ]
