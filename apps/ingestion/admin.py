from django.contrib import admin
from unfold.admin import ModelAdmin

from .models import IngestionRun


@admin.register(IngestionRun)
class IngestionRunAdmin(ModelAdmin):
    list_display = [
        "house",
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
