from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path
from unfold.admin import ModelAdmin, TabularInline

from apps.ingestion.sync import enqueue_manual_links

from .admin_cache import ActivityCacheAdminMixin
from .admin_forms import PropositionLinksForm
from .models import (
    AssessmentOrganization,
    Proposition,
    PropositionAnalysis,
    PropositionAnnotation,
    PropositionAuthor,
    PropositionEvent,
    PropositionRapporteur,
)


class AuthorInline(TabularInline):
    model = PropositionAuthor
    extra = 0
    fields = [
        "parliamentarian",
        "institutional_author",
        "party",
        "state_at_authorship",
        "order_index",
    ]
    autocomplete_fields = ["parliamentarian", "party"]


class RapporteurInline(TabularInline):
    model = PropositionRapporteur
    extra = 0
    fields = ["parliamentarian", "party", "designated_at", "ended_at"]
    autocomplete_fields = ["parliamentarian", "party"]
    readonly_fields = ["is_current"]

    @admin.display(description="Vigente", boolean=True)
    def is_current(self, obj):
        return obj.is_current


class AnalysisInline(TabularInline):
    model = PropositionAnalysis
    extra = 0
    fields = [
        "analysis_status",
        "theme_category",
        "theme_confidence",
        "classification",
        "classification_probability",
        "quiterometer_score",
        "llm_position",
        "ai_summary",
    ]


class AnnotationInline(TabularInline):
    model = PropositionAnnotation
    extra = 0
    # `legacy_theme` fica fora: o tema livre foi substituído pelo select de
    # `category`, e o texto antigo é histórico (visível só no form da anotação).
    fields = ["organization", "is_favorable", "has_caveats", "relevance", "category", "comments"]
    autocomplete_fields = ["organization"]


@admin.register(Proposition)
class PropositionAdmin(ModelAdmin):
    change_list_template = "admin/propositions/proposition/change_list.html"
    list_display = [
        "number_label",
        "year",
        "house",
        "type_code",
        "is_approved",
        "is_active",
        "presented_at",
    ]
    list_editable = ["is_approved"]
    # EmptyFieldListFilter cobre NULL e '' — os dois estados de "sem inteiro
    # teor" (ex.: OCR que não rodou ou falhou).
    list_filter = [
        "house",
        "is_approved",
        "is_active",
        "type_code",
        ("full_text", admin.EmptyFieldListFilter),
    ]
    search_fields = ["number_label", "ementa", "keywords"]
    readonly_fields = ["created_at", "updated_at"]
    inlines = [AuthorInline, RapporteurInline, AnalysisInline, AnnotationInline]
    ordering = ["-presented_at"]

    def get_urls(self):
        return [
            path(
                "add-links/",
                self.admin_site.admin_view(self.add_links),
                name="propositions_proposition_add_links",
            ),
        ] + super().get_urls()

    def add_links(self, request):
        if not self.has_add_permission(request):
            raise PermissionDenied

        form = PropositionLinksForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            runs = enqueue_manual_links(form.cleaned_data["links"])
            count = len(form.cleaned_data["links"])
            run_ids = ", ".join(str(run.pk) for run in runs)
            self.message_user(
                request,
                f"{count} proposição(ões) enfileirada(s) para coleta e avaliação. "
                f"Execução(ões): {run_ids}. Serão aprovadas automaticamente após a coleta.",
                messages.SUCCESS,
            )
            return redirect("admin:propositions_proposition_changelist")

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Adicionar proposições por link",
            "form": form,
        }
        request.current_app = self.admin_site.name
        return TemplateResponse(request, "admin/propositions/proposition/add_links.html", context)


@admin.register(PropositionEvent)
class PropositionEventAdmin(ActivityCacheAdminMixin, ModelAdmin):
    list_display = ["proposition", "event_at", "description"]
    autocomplete_fields = ["proposition"]


@admin.register(PropositionAnalysis)
class PropositionAnalysisAdmin(ModelAdmin):
    list_display = [
        "proposition",
        "analysis_status",
        "theme_category",
        "classification",
        "quiterometer_score",
        "analyzed_at",
    ]
    readonly_fields = ["analyzed_at", "completed_at", "model_id", "model_revision", "input_hash"]


@admin.register(AssessmentOrganization)
class AssessmentOrganizationAdmin(ActivityCacheAdminMixin, ModelAdmin):
    list_display = ["name", "created_at"]
    search_fields = ["name"]


@admin.register(PropositionAnnotation)
class PropositionAnnotationAdmin(ModelAdmin):
    list_display = [
        "proposition",
        "organization",
        "category",
        "is_favorable",
        "has_caveats",
        "relevance",
    ]
    # full_text é da Proposition, não da anotação: filtra as anotações cuja
    # proposição está sem inteiro teor (linhas inúteis para o dataset de treino).
    list_filter = [
        "category",
        "organization",
        "is_favorable",
        "has_caveats",
        "relevance",
        ("proposition__full_text", admin.EmptyFieldListFilter),
    ]
    search_fields = ["legacy_theme", "comments"]
    autocomplete_fields = ["proposition", "organization"]
    # `legacy_theme` é o tema livre da planilha: consultável, nunca editável.
    readonly_fields = ["legacy_theme", "created_at", "updated_at"]
