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

    publication_url = models.URLField(verbose_name="URL da publicação")
    week_start = models.DateField(verbose_name="Início da semana")
    week_end = models.DateField(
        verbose_name="Fim da semana", help_text="Segunda-feira seguinte, exclusiva."
    )
    title = models.CharField(verbose_name="Título", max_length=200)
    status = models.CharField(
        verbose_name="Situação", max_length=20, choices=Status.choices, default=Status.COLLECTING
    )
    collection = models.JSONField(verbose_name="Dados da coleta", default=dict)
    is_complete = models.BooleanField(verbose_name="Coleta completa", default=False)
    snapshot = models.JSONField(verbose_name="Retrato dos dados", default=list)
    markdown = models.TextField(verbose_name="Conteúdo em Markdown", blank=True)
    html = models.TextField(verbose_name="Conteúdo em HTML", blank=True)
    draft_id = models.BigIntegerField(
        verbose_name="Identificador do rascunho", null=True, blank=True
    )
    draft_url = models.URLField(verbose_name="URL do rascunho", blank=True)
    error = models.TextField(verbose_name="Erro", blank=True)
    deadline_missed = models.BooleanField(verbose_name="Prazo excedido", default=False)
    attempt_started_at = models.DateTimeField(
        verbose_name="Tentativa iniciada em", null=True, blank=True
    )
    delivered_at = models.DateTimeField(verbose_name="Entregue em", null=True, blank=True)
    created_at = models.DateTimeField(verbose_name="Criado em", auto_now_add=True)
    updated_at = models.DateTimeField(verbose_name="Atualizado em", auto_now=True)

    class Meta:
        verbose_name = "Relatório semanal"
        verbose_name_plural = "Relatórios semanais"
        ordering = ["-week_start"]
        constraints = [
            models.UniqueConstraint(
                fields=["publication_url", "week_start"], name="weekly_report_publication_week"
            )
        ]

    def __str__(self):
        return self.title
