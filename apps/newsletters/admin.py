from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.urls import path
from django.utils.html import format_html
from unfold.admin import ModelAdmin

from .models import WeeklyReport
from .tasks import deliver_weekly_report


@admin.register(WeeklyReport)
class WeeklyReportAdmin(ModelAdmin):
    list_display = ["title", "status", "is_complete", "deadline_missed", "draft_link", "exports"]
    list_filter = ["status", "is_complete", "deadline_missed"]
    readonly_fields = [field.name for field in WeeklyReport._meta.fields]
    actions = ["retry_delivery"]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_urls(self):
        return [
            path(
                "<int:report_id>/export/<str:kind>/",
                self.admin_site.admin_view(self.export_report),
                name="newsletters_weeklyreport_export",
            )
        ] + super().get_urls()

    def export_report(self, request, report_id, kind):
        report = get_object_or_404(WeeklyReport, pk=report_id)
        if not self.has_view_permission(request, report):
            raise PermissionDenied
        if kind not in {"markdown", "html"}:
            from django.http import Http404

            raise Http404
        suffix = "md" if kind == "markdown" else "html"
        response = HttpResponse(
            getattr(report, kind),
            content_type="text/plain; charset=utf-8"
            if kind == "markdown"
            else "text/html; charset=utf-8",
        )
        response["Content-Disposition"] = (
            f'attachment; filename="radar-{report.week_start}.{suffix}"'
        )
        return response

    @admin.display(description="Substack")
    def draft_link(self, obj):
        return (
            format_html(
                '<a href="{}" rel="noopener" target="_blank">Abrir rascunho</a>', obj.draft_url
            )
            if obj.draft_url
            else "—"
        )

    @admin.display(description="Exportar")
    def exports(self, obj):
        from django.urls import reverse

        return format_html(
            '<a href="{}">Markdown</a> · <a href="{}">HTML</a>',
            reverse("admin:newsletters_weeklyreport_export", args=[obj.pk, "markdown"]),
            reverse("admin:newsletters_weeklyreport_export", args=[obj.pk, "html"]),
        )

    @admin.action(
        description="Repetir/reconciliar entrega sem alterar rascunhos", permissions=["change"]
    )
    def retry_delivery(self, request, queryset):
        count = 0
        for report in queryset.filter(
            status__in=[
                WeeklyReport.Status.FAILED,
                WeeklyReport.Status.AUTH_REQUIRED,
                WeeklyReport.Status.UNCERTAIN,
                WeeklyReport.Status.DELIVERING,
            ]
        ):
            deliver_weekly_report.delay(report.pk, manual=True)
            count += 1
        self.message_user(
            request,
            f"{count} entrega(s) enfileirada(s). Entregas incertas apenas procuram o rascunho existente.",
            messages.INFO,
        )
