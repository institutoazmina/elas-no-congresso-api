from django.db import models


class WeeklyReport(models.Model):
    class Status(models.TextChoices):
        COLLECTING = "collecting", "Coletando"
        READY = "ready", "Preparado"
        DELIVERING = "delivering", "Enviando rascunho"
        DELIVERED = "delivered", "Rascunho criado"
        AUTH_REQUIRED = "auth_required", "Renovar sessão"
        FAILED = "failed", "Falha na entrega"
        UNCERTAIN = "uncertain", "Reconciliar entrega"

    publication_url = models.URLField()
    week_start = models.DateField()
    week_end = models.DateField(help_text="Segunda-feira seguinte, exclusiva.")
    title = models.CharField(max_length=200)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.COLLECTING)
    collection = models.JSONField(default=dict)
    is_complete = models.BooleanField(default=False)
    snapshot = models.JSONField(default=list)
    markdown = models.TextField(blank=True)
    html = models.TextField(blank=True)
    draft_id = models.BigIntegerField(null=True, blank=True)
    draft_url = models.URLField(blank=True)
    error = models.TextField(blank=True)
    deadline_missed = models.BooleanField(default=False)
    attempt_started_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-week_start"]
        constraints = [
            models.UniqueConstraint(
                fields=["publication_url", "week_start"], name="weekly_report_publication_week"
            )
        ]

    def __str__(self):
        return self.title
