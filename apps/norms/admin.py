from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import LegalNorm, PropositionAmend


@admin.register(LegalNorm)
class LegalNormAdmin(ModelAdmin):
    list_display = ["official_name", "type", "number", "year", "published_at"]
    list_filter = ["type"]
    search_fields = ["official_name", "popular_name"]


@admin.register(PropositionAmend)
class PropositionAmendAdmin(ModelAdmin):
    list_display = ["proposition", "norm", "relation_type"]
    autocomplete_fields = ["proposition", "norm"]
