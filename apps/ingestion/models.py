from django.db import models

from apps.core.enums import House


class RelevanceTerm(models.Model):
    """Palavra-chave do filtro de relevância (`theme_assert`), editável no admin.

    Permite à operação ajustar os termos sem mexer no código. Ao salvar/excluir,
    um signal limpa o cache de `theme_assert`.
    """

    class Mode(models.TextChoices):
        STANDALONE = "standalone", "Isolado (relevante por si só)"
        COMBINED = "combined", "Combinado (só com 'mulher' no texto)"

    term = models.TextField()
    mode = models.CharField(max_length=12, choices=Mode.choices, default=Mode.STANDALONE)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "relevance_terms"
        verbose_name = "Termo de relevância"
        verbose_name_plural = "Termos de relevância"
        constraints = [
            models.UniqueConstraint(fields=["term", "mode"], name="relevance_terms_term_mode")
        ]
        indexes = [models.Index(fields=["mode", "is_active"], name="idx_relevance_mode_active")]

    def __str__(self):
        return f"{self.term} ({self.mode})"


class IngestionRun(models.Model):
    """Auditoria de cada execução de coleta (substitui os .log do bot antigo)."""

    class Status(models.TextChoices):
        RUNNING = "running", "Em execução"
        SUCCESS = "success", "Sucesso"
        FAILED = "failed", "Falha"

    house = models.CharField(max_length=10, choices=House.choices)
    window_start = models.DateField()
    window_end = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.RUNNING)
    fetched_count = models.IntegerField(default=0)
    relevant_count = models.IntegerField(default=0)
    upserted_count = models.IntegerField(default=0)
    error_count = models.IntegerField(default=0)
    error_detail = models.TextField(null=True, blank=True)
    kind = models.CharField(max_length=16, default="daily")
    discovery_complete = models.BooleanField(default=False)
    processed_count = models.PositiveIntegerField(default=0)
    skipped_count = models.PositiveIntegerField(default=0)
    checkpoint_until = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "ingestion_runs"
        indexes = [
            models.Index(fields=["house", "-started_at"], name="idx_ingestion_house_date"),
        ]

    def __str__(self):
        return f"{self.house} {self.window_start}→{self.window_end} ({self.status})"


class IngestionCheckpoint(models.Model):
    house = models.CharField(max_length=10, choices=House.choices, unique=True)
    covered_since = models.DateField(null=True, blank=True)
    covered_until = models.DateTimeField(null=True, blank=True)
    baseline_complete = models.BooleanField(default=False)
    active_run = models.ForeignKey(IngestionRun, null=True, blank=True, on_delete=models.SET_NULL)
    updated_at = models.DateTimeField(auto_now=True)


class IngestionItem(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        SUCCEEDED = "succeeded", "Concluído"
        SKIPPED = "skipped", "Ignorado"
        FAILED = "failed", "Falhou"

    run = models.ForeignKey(IngestionRun, on_delete=models.CASCADE, related_name="items")
    external_id = models.BigIntegerField()
    summary = models.JSONField(default=dict)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveIntegerField(default=0)
    error = models.CharField(max_length=200, blank=True)
    processed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["run", "status"], name="idx_ingestion_item_status")]
        constraints = [
            models.UniqueConstraint(fields=["run", "external_id"], name="ingestion_run_source_item")
        ]
