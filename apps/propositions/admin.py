from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from .models import (
    Proposition,
    PropositionAnalysis,
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


@admin.register(Proposition)
class PropositionAdmin(ModelAdmin):
    list_display = ["number_label", "year", "house", "type_code", "is_active", "presented_at"]
    list_filter = ["house", "is_active", "type_code"]
    search_fields = ["number_label", "ementa", "keywords"]
    readonly_fields = ["created_at", "updated_at"]
    inlines = [AuthorInline, RapporteurInline, AnalysisInline]
    ordering = ["-presented_at"]


@admin.register(PropositionEvent)
class PropositionEventAdmin(ModelAdmin):
    list_display = ["proposition", "event_at", "description"]
    autocomplete_fields = ["proposition"]


@admin.register(PropositionAnalysis)
class PropositionAnalysisAdmin(ModelAdmin):
    list_display = ["proposition", "classification", "quiterometer_score", "analyzed_at"]
    readonly_fields = ["analyzed_at"]
