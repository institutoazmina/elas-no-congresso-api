from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect
from django.template.response import TemplateResponse
from django.urls import path
from unfold.admin import ModelAdmin, TabularInline

from apps.ingestion.tasks import enrich_parliamentarian_profiles

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

    @admin.display(description="Vigente", boolean=True)
    def is_current(self, obj):
        return obj.is_current


class ContactInline(TabularInline):
    model = ParliamentarianContact
    extra = 0
    fields = ["channel", "value", "is_public"]


@admin.register(Parliamentarian)
class ParliamentarianAdmin(ModelAdmin):
    change_list_template = "admin/legislatures/parliamentarian/change_list.html"
    list_display = ["full_name", "social_name", "gender", "birth_date"]
    list_filter = ["gender"]
    search_fields = ["full_name", "social_name"]
    inlines = [TermInline, ContactInline]
    readonly_fields = ["created_at", "updated_at"]
    ordering = ["full_name"]

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                "enrich-profiles/",
                self.admin_site.admin_view(self.enrich_profiles),
                name="legislatures_parliamentarian_enrich_profiles",
            ),
        ]
        return custom_urls + urls

    def enrich_profiles(self, request):
        if not self.has_change_permission(request):
            raise PermissionDenied

        if request.method == "POST":
            task = enrich_parliamentarian_profiles.delay()  # type: ignore[attr-defined]
            self.message_user(
                request,
                f"Enriquecimento de perfis parlamentares iniciado. ID da tarefa: {task.id}",
                messages.SUCCESS,
            )
            return redirect("admin:legislatures_parliamentarian_changelist")

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": "Enriquecer perfis parlamentares",
            "subtitle": None,
        }
        request.current_app = self.admin_site.name
        return TemplateResponse(
            request,
            "admin/legislatures/parliamentarian/enrich_profiles.html",
            context,
        )


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
