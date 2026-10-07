from django.db import models

from apps.core.enums import House, HumanRelevance, PropositionCategory
from apps.legislatures.models import InstitutionalAuthor, Parliamentarian, Party


class Proposition(models.Model):
    house = models.CharField(max_length=10, choices=House.choices)
    external_id = models.BigIntegerField()
    type_code = models.TextField()
    number_label = models.TextField()
    number = models.IntegerField()
    year = models.SmallIntegerField()
    presented_at = models.DateField()
    ementa = models.TextField()
    keywords = models.TextField(null=True, blank=True)
    full_text_url = models.TextField(null=True, blank=True)
    full_text = models.TextField(null=True, blank=True)
    source_checked_at = models.DateTimeField(null=True, blank=True, db_index=True)
    reconciled_at = models.DateTimeField(null=True, blank=True, db_index=True)
    current_content = models.ForeignKey(
        "PropositionContentVersion",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="selected_by",
    )
    tramitation_url = models.TextField(null=True, blank=True)
    current_status = models.TextField(null=True, blank=True)
    current_status_code = models.IntegerField(null=True, blank=True)
    regime = models.TextField(null=True, blank=True)
    scope = models.TextField(null=True, blank=True)
    appreciation_mode = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    # A coleta é intencionalmente abrangente. A publicação, porém, exige
    # curadoria: uma proposição nova não pode aparecer no painel público até
    # que alguém da equipe a aprove no gerenciador.
    is_approved = models.BooleanField(default=False, db_index=True)
    enacted_law_type = models.TextField(null=True, blank=True)
    enacted_law_number = models.IntegerField(null=True, blank=True)
    enacted_law_year = models.SmallIntegerField(null=True, blank=True)
    enacted_at = models.DateField(null=True, blank=True)
    originating_house = models.CharField(
        max_length=10, choices=House.choices, null=True, blank=True
    )
    raw_payload = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "propositions"
        constraints = [
            models.UniqueConstraint(
                fields=["house", "external_id"], name="propositions_house_external_id"
            )
        ]
        indexes = [
            models.Index(fields=["house", "-year"], name="idx_prop_house_year"),
            models.Index(fields=["-presented_at"], name="idx_prop_presented"),
            models.Index(fields=["type_code", "-year"], name="idx_prop_type"),
        ]

    def __str__(self):
        return f"{self.number_label} ({self.year})"


class PropositionEvent(models.Model):
    proposition = models.ForeignKey(Proposition, on_delete=models.CASCADE, related_name="events")
    # Identificador estável da API de origem. Evita duplicar o histórico em
    # reprocessamentos diários e no backfill inicial.
    source_event_id = models.CharField(max_length=128, null=True, blank=True)
    source_kind = models.CharField(max_length=32, default="status")
    event_at = models.DateTimeField()
    sequence = models.IntegerField(null=True, blank=True)
    title = models.TextField(null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    situation = models.TextField(null=True, blank=True)
    dispatch = models.TextField(null=True, blank=True)
    committee_id = models.BigIntegerField(null=True, blank=True)
    committee_acronym = models.CharField(max_length=32, null=True, blank=True)
    committee_name = models.TextField(null=True, blank=True)
    is_countable = models.BooleanField(default=True)
    raw_payload = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "proposition_events"
        indexes = [
            models.Index(fields=["proposition", "-event_at"], name="idx_events_prop_date"),
            models.Index(fields=["-event_at"], name="idx_events_date"),
            models.Index(fields=["proposition", "source_event_id"], name="idx_events_prop_source"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["proposition", "source_event_id"],
                condition=models.Q(source_event_id__isnull=False),
                name="proposition_events_source_id",
            )
        ]


class PropositionAuthor(models.Model):
    proposition = models.ForeignKey(Proposition, on_delete=models.CASCADE, related_name="authors")
    parliamentarian = models.ForeignKey(
        Parliamentarian,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="authored_propositions",
    )
    institutional_author = models.ForeignKey(
        InstitutionalAuthor,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="authored_propositions",
    )
    party = models.ForeignKey(
        Party,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="authored_propositions",
    )
    state_at_authorship = models.CharField(max_length=2, null=True, blank=True)
    order_index = models.SmallIntegerField(default=1)

    class Meta:
        db_table = "proposition_authors"
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(parliamentarian__isnull=False)
                    | models.Q(institutional_author__isnull=False)
                ),
                name="proposition_authors_at_least_one_author",
            )
        ]
        indexes = [
            models.Index(fields=["parliamentarian"], name="idx_authors_parl"),
            models.Index(fields=["party"], name="idx_authors_party"),
        ]


class PropositionRapporteur(models.Model):
    proposition = models.ForeignKey(
        Proposition, on_delete=models.CASCADE, related_name="rapporteurs"
    )
    parliamentarian = models.ForeignKey(
        Parliamentarian, on_delete=models.RESTRICT, related_name="rapporteurships"
    )
    committee_id = models.BigIntegerField(null=True, blank=True)
    party = models.ForeignKey(
        Party, on_delete=models.SET_NULL, null=True, blank=True, related_name="rapporteurships"
    )
    designated_at = models.DateField()
    ended_at = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "proposition_rapporteurs"
        indexes = [
            models.Index(fields=["proposition"], name="idx_rapp_prop"),
            models.Index(fields=["parliamentarian"], name="idx_rapp_parl_current"),
        ]

    @property
    def is_current(self):
        return self.ended_at is None


class PropositionAnalysis(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        SUCCEEDED = "succeeded", "Concluída"
        FAILED = "failed", "Falhou"

    proposition = models.OneToOneField(
        Proposition, on_delete=models.CASCADE, primary_key=True, related_name="analysis"
    )
    # Resultado do modelo ``tema``. A categoria usa exatamente a taxonomia
    # editorial do produto; os scores brutos ficam guardados para auditoria.
    theme_category = models.CharField(
        max_length=32, choices=PropositionCategory.choices, null=True, blank=True
    )
    theme_confidence = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    theme_scores = models.JSONField(default=dict, blank=True)
    # Resultado do modelo ``favorabilidade``. ``classification`` mantém o
    # índice decidido pelo cutoff e ``classification_probability`` é P(classe 1
    # = desfavorável), preservando os campos já existentes.
    classification = models.SmallIntegerField(null=True, blank=True)
    classification_probability = models.DecimalField(
        max_digits=5, decimal_places=4, null=True, blank=True
    )
    favorability_scores = models.JSONField(default=dict, blank=True)
    llm_position = models.SmallIntegerField(null=True, blank=True)
    final_position_score = models.DecimalField(
        max_digits=5, decimal_places=4, null=True, blank=True
    )
    expert_opinion = models.TextField(null=True, blank=True)
    expert_id = models.BigIntegerField(null=True, blank=True)
    ai_summary = models.TextField(null=True, blank=True)
    quiterometer_score = models.FloatField(null=True, blank=True)
    model_id = models.CharField(max_length=128, null=True, blank=True)
    model_revision = models.CharField(max_length=64, null=True, blank=True)
    input_hash = models.CharField(max_length=64, null=True, blank=True)
    analysis_status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING
    )
    analysis_error = models.TextField(null=True, blank=True)
    analyzed_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    content_version = models.ForeignKey(
        "PropositionContentVersion",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="analyses",
    )

    class Meta:
        db_table = "proposition_analysis"
        indexes = [
            models.Index(fields=["quiterometer_score"], name="idx_analysis_quitero"),
            models.Index(fields=["analysis_status"], name="idx_analysis_status"),
        ]


class PropositionDocument(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        FETCHING = "fetching", "Extraindo"
        READY = "ready", "Verificado"
        FAILED = "failed", "Falhou"

    proposition = models.ForeignKey(Proposition, on_delete=models.CASCADE, related_name="documents")
    source_key = models.CharField(max_length=128)
    role = models.CharField(
        max_length=16, choices=[("original", "Original"), ("replacement", "Texto substitutivo")]
    )
    url = models.TextField()
    source_revision = models.CharField(max_length=64)
    checked_revision = models.CharField(max_length=64, blank=True)
    analyze_on_first = models.BooleanField(default=True)
    source_date = models.DateTimeField(null=True, blank=True)
    etag = models.TextField(blank=True)
    last_modified = models.TextField(blank=True)
    bytes_hash = models.CharField(max_length=64, blank=True)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    attempts = models.PositiveIntegerField(default=0)
    attempted_at = models.DateTimeField(null=True, blank=True)
    checked_at = models.DateTimeField(null=True, blank=True)
    error = models.CharField(max_length=200, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["proposition", "source_key"], name="proposition_document_source"
            )
        ]


class PropositionContentVersion(models.Model):
    proposition = models.ForeignKey(
        Proposition, on_delete=models.CASCADE, related_name="content_versions"
    )
    document = models.ForeignKey(
        PropositionDocument,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="versions",
    )
    text = models.TextField()
    text_hash = models.CharField(max_length=64)
    source_url = models.TextField(blank=True)
    source_revision = models.CharField(max_length=64, blank=True)
    source_date = models.DateTimeField(null=True, blank=True)
    extraction_version = models.CharField(max_length=32, default="pdf-ocr-v1")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["proposition", "document", "text_hash", "source_revision"],
                name="proposition_content_document_hash",
                nulls_distinct=False,
            )
        ]


class ClassificationRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        RUNNING = "running", "Em execução"
        SUCCEEDED = "succeeded", "Concluída"
        FAILED = "failed", "Falhou"
        SUPERSEDED = "superseded", "Substituída"

    proposition = models.ForeignKey(
        Proposition, on_delete=models.CASCADE, related_name="classification_requests"
    )
    content_version = models.ForeignKey(
        PropositionContentVersion, on_delete=models.CASCADE, related_name="classification_requests"
    )
    content_hash = models.CharField(max_length=64)
    configuration_hash = models.CharField(max_length=64)
    input_text = models.TextField()
    input_hash = models.CharField(max_length=64)
    model_id = models.CharField(max_length=128)
    model_revision = models.CharField(max_length=64)
    threshold = models.FloatField()
    only_if_unevaluated = models.BooleanField(default=False)
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING, db_index=True
    )
    attempts = models.PositiveIntegerField(default=0)
    attempted_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    result = models.JSONField(default=dict)
    error = models.CharField(max_length=200, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["proposition", "content_hash", "configuration_hash"],
                name="classification_content_configuration",
            )
        ]


class AssessmentOrganization(models.Model):
    """Organização da sociedade civil que avalia proposições (avaliadora)."""

    name = models.TextField(unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "assessment_organizations"

    def __str__(self):
        return self.name


class PropositionAnnotation(models.Model):
    """Anotação humana de uma avaliadora sobre uma proposição."""

    proposition = models.ForeignKey(
        Proposition, on_delete=models.CASCADE, related_name="annotations"
    )
    organization = models.ForeignKey(
        AssessmentOrganization, on_delete=models.PROTECT, related_name="annotations"
    )
    # Avaliação: Favorável -> True, Desfavorável -> False, vazio -> NULL
    is_favorable = models.BooleanField(null=True, blank=True)
    # Há ressalvas?: S -> True, N/vazio -> False
    has_caveats = models.BooleanField(default=False)
    relevance = models.CharField(
        max_length=20, choices=HumanRelevance.choices, default=HumanRelevance.RELEVANTE
    )
    # nota av (1 / -1) e nota rel (2 / 1)
    assessment_score = models.SmallIntegerField(null=True, blank=True)
    relevance_score = models.SmallIntegerField(null=True, blank=True)
    # Categorias 2026: taxonomia fechada, obrigatória. Substitui o antigo
    # `human_theme` como campo de trabalho das avaliadoras.
    category = models.CharField(max_length=32, choices=PropositionCategory.choices)
    # Antigo `human_theme` ("Tema (class humana)"): texto livre da planilha, com
    # granularidade que as 10 categorias colapsam (Feminicídio, Lei Maria da
    # Penha, Microcefalia...). Preservado como histórico, fora dos formulários.
    legacy_theme = models.TextField(null=True, blank=True)
    comments = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "proposition_annotations"
        constraints = [
            # `choices` só vale em forms/full_clean; o check garante no banco
            # que scripts e shell também fiquem dentro da taxonomia.
            models.CheckConstraint(
                condition=models.Q(category__in=PropositionCategory.values),
                name="proposition_annotations_category_check",
            ),
        ]

    def save(self, *args, **kwargs):
        # Invariante: relevance nunca é nulo — cai em 'relevante' se vier None.
        if self.relevance is None:
            self.relevance = HumanRelevance.RELEVANTE
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.organization} · {self.proposition}"


class PropositionEmbedding(models.Model):
    proposition = models.OneToOneField(
        Proposition, on_delete=models.CASCADE, primary_key=True, related_name="embedding"
    )
    model_name = models.TextField()
    # VectorField requires pgvector; migration adds HNSW index via RunSQL
    embedding = models.BinaryField()  # overridden via RunSQL ALTER COLUMN in migration
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "proposition_embeddings"
