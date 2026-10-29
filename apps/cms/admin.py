from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.core.paginator import Paginator
from django.db.models import Q
from django.forms import modelform_factory
from django.shortcuts import redirect, render
from django.urls import path, reverse
from django.utils.decorators import method_decorator
from django.utils.html import format_html
from django.views.decorators.clickjacking import xframe_options_sameorigin
from unfold.admin import ModelAdmin, TabularInline
from unfold.widgets import UnfoldAdminTextareaWidget
from unfold_markdown.widgets import MarkdownWidget

from .images import ImageSpec, normalize, normalize_logo, normalize_unconstrained
from .models import (
    AboutPage,
    AboutPartner,
    AboutTeamMember,
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
    FooterFunder,
    FooterSocialLink,
    HeroPage,
    HomePage,
    MarkdownImage,
    ReportsPage,
)


class CmsMarkdownWidget(MarkdownWidget):
    template_name = "cms/widgets/markdown.html"

    class Media:
        extend = False
        css = {
            "all": (
                "unfold_markdown/css/easymde.min.css",
                "unfold_markdown/css/markdown.css",
                "cms/css/markdown-components.css",
            )
        }
        js = (
            "unfold_markdown/js/easymde.min.js",
            "unfold_markdown/js/markdown.config.js",
            "cms/js/markdown-components.js",
            "cms/js/markdown-image-chooser.js",
        )

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        context["widget"]["image_chooser_url"] = reverse("admin:cms_markdownimage_chooser")
        return context


FeministAIMarkdownWidget = CmsMarkdownWidget


class MarkdownImageForm(forms.ModelForm):
    class Meta:
        model = MarkdownImage
        fields = ["title", "alt_text", "image"]

    def clean_image(self):
        image = self.cleaned_data["image"]
        if isinstance(image, UploadedFile):
            return normalize_unconstrained(image, stem=self.instance.pk.hex)
        return image


@admin.register(MarkdownImage)
class MarkdownImageAdmin(ModelAdmin):
    form = MarkdownImageForm
    list_display = ["thumbnail", "title", "alt_text", "dimensions", "uploaded_by", "created_at"]
    search_fields = ["title", "alt_text"]
    readonly_fields = ["preview", "width", "height", "uploaded_by", "created_at", "updated_at"]
    fields = [
        "preview",
        "title",
        "alt_text",
        "image",
        "width",
        "height",
        "uploaded_by",
        "created_at",
        "updated_at",
    ]

    @admin.display(description="Prévia")
    def thumbnail(self, obj):
        return format_html(
            '<img src="{}" alt="" style="width:72px;height:48px;object-fit:cover;border-radius:6px">',
            obj.image.url,
        )

    @admin.display(description="Imagem")
    def preview(self, obj):
        if not obj:
            return "—"
        return format_html(
            '<img src="{}" alt="" style="max-width:480px;max-height:320px;object-fit:contain">',
            obj.image.url,
        )

    @admin.display(description="Dimensões")
    def dimensions(self, obj):
        return f"{obj.width} × {obj.height} px"

    def save_model(self, request, obj, form, change):
        if not obj.uploaded_by_id:
            obj.uploaded_by = request.user
        super().save_model(request, obj, form, change)

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and not (obj and obj.is_referenced)

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions

    def get_urls(self):
        return [
            path(
                "chooser/",
                self.admin_site.admin_view(self.chooser_view),
                name="cms_markdownimage_chooser",
            )
        ] + super().get_urls()

    @method_decorator(xframe_options_sameorigin)
    def chooser_view(self, request):
        if not self.has_view_permission(request):
            raise PermissionDenied

        form = MarkdownImageForm()
        if request.method == "POST":
            if not self.has_add_permission(request):
                raise PermissionDenied
            form = MarkdownImageForm(request.POST, request.FILES)
            if form.is_valid():
                image = form.save(commit=False)
                image.uploaded_by = request.user
                image.save()
                messages.success(request, "Imagem adicionada à galeria.")
                form = MarkdownImageForm()

        query = request.GET.get("q", "").strip()
        images = self.get_queryset(request)
        if query:
            images = images.filter(Q(title__icontains=query) | Q(alt_text__icontains=query))
        page_obj = Paginator(images, 24).get_page(request.GET.get("page"))
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Galeria de imagens",
            "form": form,
            "page_obj": page_obj,
            "query": query,
            "can_add": self.has_add_permission(request),
            "is_popup": True,
        }
        return render(request, "admin/cms/markdownimage/chooser.html", context)


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
        fields=[
            "seo_title",
            "seo_description",
            "title",
            "subtitle",
            "hero_image",
            "hero_image_alt",
        ],
        widgets={"subtitle": UnfoldAdminTextareaWidget(attrs={"rows": 3})},
    )


class HeroPageAdmin(CmsPageAdmin):
    fieldsets = [
        ("SEO", {"fields": ["seo_title", "seo_description"]}),
        (
            "Topo da página",
            {"fields": ["title", "subtitle", "hero_image", "hero_image_alt"]},
        ),
        ("Publicação", {"fields": ["updated_at"]}),
    ]


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
        fields = [
            "seo_title",
            "seo_description",
            "hero_title",
            "hero_description",
            "hero_image",
            "hero_image_alt",
            "content",
        ]
        widgets = {"content": FeministAIMarkdownWidget()}

    def image_specs(self):
        return {"hero_image": (None, "hero")}


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
        ("SEO", {"fields": ["seo_title", "seo_description"]}),
        (
            "Topo da página",
            {"fields": ["hero_title", "hero_description", "hero_image", "hero_image_alt"]},
        ),
        ("Corpo da página em Markdown", {"fields": ["content"]}),
        ("Publicação", {"fields": ["updated_at"]}),
    ]


class AboutPageForm(CmsPageForm):
    class Meta:
        model = AboutPage
        fields = [
            "seo_title",
            "seo_description",
            "hero_title",
            "hero_description",
            "hero_image",
            "hero_image_alt",
            "content",
        ]
        widgets = {"content": CmsMarkdownWidget()}

    def image_specs(self):
        return {"hero_image": (None, "hero")}


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


class AboutTeamMemberInline(TabularInline):
    model = AboutTeamMember
    fields = ["group", "position", "name", "role"]
    extra = 0


@admin.register(AboutPage)
class AboutPageAdmin(CmsPageAdmin):
    form = AboutPageForm
    fieldsets = [
        ("SEO", {"fields": ["seo_title", "seo_description"]}),
        (
            "Topo da página",
            {"fields": ["hero_title", "hero_description", "hero_image", "hero_image_alt"]},
        ),
        ("Corpo da página em Markdown", {"fields": ["content"]}),
        ("Publicação", {"fields": ["updated_at"]}),
    ]
    inlines = [AboutPartnerInline, AboutTeamMemberInline]


class HomePageForm(CmsPageForm):
    class Meta:
        model = HomePage
        fields = [
            "seo_title",
            "seo_description",
            "hero_title",
            "hero_description",
            "hero_cta_text",
            "hero_image",
            "hero_image_alt",
            "content",
        ]
        widgets = {
            "hero_title": UnfoldAdminTextareaWidget(attrs={"rows": 2}),
            "content": CmsMarkdownWidget(),
        }

    def image_specs(self):
        return {"hero_image": (None, "hero")}


@admin.register(HomePage)
class HomePageAdmin(CmsPageAdmin):
    form = HomePageForm
    fieldsets = [
        ("SEO", {"fields": ["seo_title", "seo_description"]}),
        (
            "Topo da página",
            {
                "fields": [
                    "hero_title",
                    "hero_description",
                    "hero_cta_text",
                    "hero_image",
                    "hero_image_alt",
                ]
            },
        ),
        ("Corpo da página em Markdown", {"fields": ["content"]}),
        ("Publicação", {"fields": ["updated_at"]}),
    ]


class FooterSocialLinkInline(TabularInline):
    model = FooterSocialLink
    fields = ["position", "icon", "label", "url"]
    extra = 0


class FooterFunderForm(forms.ModelForm):
    class Meta:
        model = FooterFunder
        fields = "__all__"

    def clean_logo_image(self):
        value = self.cleaned_data.get("logo_image")
        if isinstance(value, UploadedFile):
            return normalize_logo(value)
        return value


class FooterFunderInline(TabularInline):
    model = FooterFunder
    form = FooterFunderForm
    fields = ["position", "name", "logo_image"]
    extra = 0


@admin.register(FooterAlertsPage)
class FooterAlertsPageAdmin(CmsPageAdmin):
    fieldsets = [
        (
            "Receba nossos alertas em todo o site",
            {"fields": ["title", "text", "cta_text", "cta_url", "updated_at"]},
        ),
    ]
    inlines = [FooterSocialLinkInline, FooterFunderInline]
