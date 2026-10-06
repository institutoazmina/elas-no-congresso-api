from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import IngestionCheckpoint, IngestionItem, IngestionRun, RelevanceTerm


@admin.register(RelevanceTerm)
class RelevanceTermAdmin(ModelAdmin):
    list_display = ["term", "mode", "is_active", "updated_at"]
    list_filter = ["mode", "is_active"]
    list_editable = ["is_active"]
    search_fields = ["term"]
    ordering = ["mode", "term"]
    fields = ["term", "mode", "is_active", "notes"]


@admin.register(IngestionRun)
class IngestionRunAdmin(ModelAdmin):
    list_display = [
        "house",
        "kind",
        "status",
        "window_start",
        "window_end",
        "fetched_count",
        "relevant_count",
        "upserted_count",
        "error_count",
        "started_at",
        "finished_at",
    ]
    list_filter = ["house", "status"]
    readonly_fields = [f.name for f in IngestionRun._meta.fields]
    ordering = ["-started_at"]

    def has_add_permission(self, request):
        return False


@admin.register(IngestionCheckpoint)
class IngestionCheckpointAdmin(ModelAdmin):
    list_display = ["house", "baseline_complete", "covered_since", "covered_until", "active_run"]
    readonly_fields = [f.name for f in IngestionCheckpoint._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(IngestionItem)
class IngestionItemAdmin(ModelAdmin):
    list_display = ["run", "external_id", "status", "attempts", "error", "processed_at"]
    list_filter = ["status", "run__house", "run__kind"]
    readonly_fields = [f.name for f in IngestionItem._meta.fields]

    def has_add_permission(self, request):
        return False
