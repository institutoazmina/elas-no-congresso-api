from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import AnalyticalTag, PropositionRelation, PropositionTheme, Theme


@admin.register(Theme)
class ThemeAdmin(ModelAdmin):
    list_display = ["name", "slug", "parent"]
    search_fields = ["name", "slug"]
    autocomplete_fields = ["parent"]


@admin.register(AnalyticalTag)
class AnalyticalTagAdmin(ModelAdmin):
    list_display = ["name", "slug"]
    search_fields = ["name", "slug"]


@admin.register(PropositionTheme)
class PropositionThemeAdmin(ModelAdmin):
    list_display = ["proposition", "theme", "rank"]
    autocomplete_fields = ["proposition", "theme"]


@admin.register(PropositionRelation)
class PropositionRelationAdmin(ModelAdmin):
    list_display = ["proposition", "related_proposition", "relation_type", "similarity_score"]
