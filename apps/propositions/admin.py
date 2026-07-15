from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

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
    fields = ["parliamentarian", "institutional_author", "party", "state_at_authorship", "order_index"]
    autocomplete_fields = ["parliamentarian", "party"]


class RapporteurInline(TabularInline):
    model = PropositionRapporteur
    extra = 0
    fields = ["parliamentarian", "party", "designated_at", "ended_at"]
    autocomplete_fields = ["parliamentarian", "party"]
    readonly_fields = ["is_current"]


class AnalysisInline(TabularInline):
    model = PropositionAnalysis
    extra = 0
    fields = ["classification", "quiterometer_score", "llm_position", "ai_summary"]

class AnnotationInline(TabularInline):
    model = PropositionAnnotation
    extra = 0
    fields = ["organization", "is_favorable", "has_caveats", "relevance", "human_theme", "comments"]
    autocomplete_fields = ["organization"]


@admin.register(Proposition)
class PropositionAdmin(ModelAdmin):
    list_display = ["number_label", "year", "house", "type_code", "is_active", "presented_at"]
    # EmptyFieldListFilter cobre NULL e '' — os dois estados de "sem inteiro
    # teor" (ex.: OCR que não rodou ou falhou).
    list_filter = ["house", "is_active", "type_code", ("full_text", admin.EmptyFieldListFilter)]
    search_fields = ["number_label", "ementa", "keywords"]
    readonly_fields = ["created_at", "updated_at"]
    inlines = [AuthorInline, RapporteurInline, AnalysisInline, AnnotationInline]
    ordering = ["-presented_at"]


@admin.register(PropositionEvent)
class PropositionEventAdmin(ModelAdmin):
    list_display = ["proposition", "event_at", "description"]
    autocomplete_fields = ["proposition"]


@admin.register(PropositionAnalysis)
class PropositionAnalysisAdmin(ModelAdmin):
    list_display = ["proposition", "classification", "quiterometer_score", "analyzed_at"]
    readonly_fields = ["analyzed_at"]

@admin.register(AssessmentOrganization)
class AssessmentOrganizationAdmin(ModelAdmin):
    list_display = ["name", "created_at"]
    search_fields = ["name"]

@admin.register(PropositionAnnotation)
class PropositionAnnotationAdmin(ModelAdmin):
    list_display = ["proposition", "organization", "is_favorable", "has_caveats", "relevance", "human_theme"]
    # full_text é da Proposition, não da anotação: filtra as anotações cuja
    # proposição está sem inteiro teor (linhas inúteis para o dataset de treino).
    list_filter = [
        "organization", "is_favorable", "has_caveats", "relevance",
        ("proposition__full_text", admin.EmptyFieldListFilter),
    ]
    search_fields = ["human_theme", "comments"]
    autocomplete_fields = ["proposition", "organization"]
    readonly_fields = ["created_at", "updated_at"]
