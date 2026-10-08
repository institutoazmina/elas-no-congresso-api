from django.db import models

from apps.core.enums import House


class RelevanceTerm(models.Model):
    """Palavra-chave do filtro de relevância (`theme_assert`), editável no admin.

    Permite à operação ajustar os termos sem mexer no código. Ao salvar/excluir,
    um signal limpa o cache de `theme_assert`.
    """

    class Mode(models.TextChoices):
        STANDALONE = "standalone", "Isolado (relevante por si só)"
        COMBINED = "combined", "Combinado (expressões separadas por +)"

    term = models.TextField(verbose_name="Termo")
    mode = models.CharField(
        verbose_name="Modo", max_length=12, choices=Mode.choices, default=Mode.STANDALONE
    )
    is_active = models.BooleanField(verbose_name="Ativo", default=True)
    notes = models.TextField(verbose_name="Observações", null=True, blank=True)
    created_at = models.DateTimeField(verbose_name="Criado em", auto_now_add=True)
    updated_at = models.DateTimeField(verbose_name="Atualizado em", auto_now=True)

    class Meta:
        verbose_name = "Termo de relevância"
        verbose_name_plural = "Termos de relevância"
        db_table = "relevance_terms"
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

    house = models.CharField(verbose_name="Casa legislativa", max_length=10, choices=House.choices)
    window_start = models.DateField(verbose_name="Início do período")
    window_end = models.DateField(verbose_name="Fim do período")
    status = models.CharField(
        verbose_name="Situação", max_length=10, choices=Status.choices, default=Status.RUNNING
    )
    fetched_count = models.IntegerField(verbose_name="Itens coletados", default=0)
    relevant_count = models.IntegerField(verbose_name="Itens relevantes", default=0)
    upserted_count = models.IntegerField(verbose_name="Itens inseridos ou atualizados", default=0)
    error_count = models.IntegerField(verbose_name="Erros", default=0)
    error_detail = models.TextField(verbose_name="Detalhes do erro", null=True, blank=True)
    kind = models.CharField(verbose_name="Tipo", max_length=16, default="daily")
    discovery_complete = models.BooleanField(verbose_name="Descoberta concluída", default=False)
    processed_count = models.PositiveIntegerField(verbose_name="Itens processados", default=0)
    skipped_count = models.PositiveIntegerField(verbose_name="Itens ignorados", default=0)
    checkpoint_until = models.DateTimeField(
        verbose_name="Marco de coleta até", null=True, blank=True
    )
    started_at = models.DateTimeField(verbose_name="Iniciado em", auto_now_add=True)
    finished_at = models.DateTimeField(verbose_name="Finalizado em", null=True, blank=True)

    class Meta:
        verbose_name = "Execução de coleta"
        verbose_name_plural = "Execuções de coleta"
        db_table = "ingestion_runs"
        indexes = [
            models.Index(fields=["house", "-started_at"], name="idx_ingestion_house_date"),
        ]

    def __str__(self):
        return f"{self.house} {self.window_start}→{self.window_end} ({self.status})"


class IngestionCheckpoint(models.Model):
    house = models.CharField(
        verbose_name="Casa legislativa", max_length=10, choices=House.choices, unique=True
    )
    covered_since = models.DateField(verbose_name="Cobertura desde", null=True, blank=True)
    covered_until = models.DateTimeField(verbose_name="Cobertura até", null=True, blank=True)
    baseline_complete = models.BooleanField(verbose_name="Carga inicial concluída", default=False)
    active_run = models.ForeignKey(
        IngestionRun,
        verbose_name="Coleta em andamento",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
    )
    updated_at = models.DateTimeField(verbose_name="Atualizado em", auto_now=True)

    class Meta:
        verbose_name = "Marco de coleta"
        verbose_name_plural = "Marcos de coleta"


class IngestionItem(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        SUCCEEDED = "succeeded", "Concluído"
        SKIPPED = "skipped", "Ignorado"
        FAILED = "failed", "Falhou"

    run = models.ForeignKey(
        IngestionRun,
        verbose_name="Execução de coleta",
        on_delete=models.CASCADE,
        related_name="items",
    )
    external_id = models.BigIntegerField(verbose_name="Identificador externo")
    summary = models.JSONField(verbose_name="Resumo", default=dict)
    status = models.CharField(
        verbose_name="Situação", max_length=16, choices=Status.choices, default=Status.PENDING
    )
    attempts = models.PositiveIntegerField(verbose_name="Tentativas", default=0)
    error = models.CharField(verbose_name="Erro", max_length=200, blank=True)
    processed_at = models.DateTimeField(verbose_name="Processado em", null=True, blank=True)

    class Meta:
        verbose_name = "Item de coleta"
        verbose_name_plural = "Itens de coleta"
        indexes = [models.Index(fields=["run", "status"], name="idx_ingestion_item_status")]
        constraints = [
            models.UniqueConstraint(fields=["run", "external_id"], name="ingestion_run_source_item")
        ]
