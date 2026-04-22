from django.contrib import admin
from unfold.admin import ModelAdmin, TabularInline

from .models import (
    InstitutionalAuthor,
    Legislature,
    Parliamentarian,
    ParliamentarianAsset,
    ParliamentarianContact,
    ParliamentarianExpense,
    ParliamentarianInvestigation,
    ParliamentarianTerm,
    Party,
)


@admin.register(Legislature)
class LegislatureAdmin(ModelAdmin):
    list_display = ["number", "start_date", "end_date"]
    ordering = ["-number"]


@admin.register(Party)
class PartyAdmin(ModelAdmin):
    list_display = ["acronym", "name", "ideology"]
    search_fields = ["acronym", "name"]
    ordering = ["acronym"]


class TermInline(TabularInline):
    model = ParliamentarianTerm
    extra = 0
    fields = ["house", "state", "party", "legislature_number", "start_date", "end_date"]
    readonly_fields = ["is_current"]


class ContactInline(TabularInline):
    model = ParliamentarianContact
    extra = 0
    fields = ["channel", "value", "is_public"]


@admin.register(Parliamentarian)
class ParliamentarianAdmin(ModelAdmin):
    list_display = ["full_name", "social_name", "gender", "birth_date"]
    list_filter = ["gender"]
    search_fields = ["full_name", "social_name"]
    inlines = [TermInline, ContactInline]
    readonly_fields = ["created_at", "updated_at"]
    ordering = ["full_name"]


@admin.register(ParliamentarianTerm)
class ParliamentarianTermAdmin(ModelAdmin):
    list_display = ["parliamentarian", "house", "state", "party", "start_date", "end_date"]
    list_filter = ["house", "state"]
    search_fields = ["parliamentarian__full_name", "party__acronym"]
    autocomplete_fields = ["parliamentarian", "party"]


@admin.register(ParliamentarianAsset)
class ParliamentarianAssetAdmin(ModelAdmin):
    list_display = ["parliamentarian", "reference_year", "total_value"]
    autocomplete_fields = ["parliamentarian"]


@admin.register(ParliamentarianExpense)
class ParliamentarianExpenseAdmin(ModelAdmin):
    list_display = ["parliamentarian", "reference_month", "category", "amount"]
    autocomplete_fields = ["parliamentarian"]


@admin.register(ParliamentarianInvestigation)
class ParliamentarianInvestigationAdmin(ModelAdmin):
    list_display = ["parliamentarian", "case_number", "court", "status"]
    autocomplete_fields = ["parliamentarian"]


@admin.register(InstitutionalAuthor)
class InstitutionalAuthorAdmin(ModelAdmin):
    list_display = ["name", "kind"]
    search_fields = ["name"]
