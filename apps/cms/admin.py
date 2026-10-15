from django import forms
from django.conf import settings
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.shortcuts import redirect
from django.urls import reverse
from unfold.admin import ModelAdmin
from unfold.widgets import UnfoldAdminTextareaWidget

from .images import ImageSpec, normalize
from .models import AlertsPage


class CmsPageForm(forms.ModelForm):
    # campo -> (especificação, prefixo do arquivo no bucket)
    # Imagens são obrigatórias no model: sem a opção "limpar", só substituir.
    image_specs: dict[str, tuple[ImageSpec, str]] = {}

    def clean(self):
        cleaned = super().clean()
        for field, (spec, stem) in self.image_specs.items():
            value = cleaned.get(field)
            if isinstance(value, UploadedFile):
                try:
                    cleaned[field] = normalize(value, spec, stem=stem)
                except ValidationError as exc:
                    self.add_error(field, exc)
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


class AlertsPageForm(CmsPageForm):
    image_specs = {"hero_image": (AlertsPage.HERO_IMAGE, "hero")}

    class Meta:
        model = AlertsPage
        fields = ["title", "subtitle", "hero_image"]
        widgets = {"subtitle": UnfoldAdminTextareaWidget(attrs={"rows": 3})}


@admin.register(AlertsPage)
class AlertsPageAdmin(CmsPageAdmin):
    form = AlertsPageForm
    fieldsets = [("Topo da página", {"fields": ["title", "subtitle", "hero_image", "updated_at"]})]
