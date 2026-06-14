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
    started_at = models.DateTimeField(auto_now_add=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "ingestion_runs"
        indexes = [
            models.Index(fields=["house", "-started_at"], name="idx_ingestion_house_date"),
        ]

    def __str__(self):
        return f"{self.house} {self.window_start}→{self.window_end} ({self.status})"
