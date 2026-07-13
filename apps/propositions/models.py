from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.db.models import GeneratedField

from apps.core.enums import House, HumanRelevance
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
    tramitation_url = models.TextField(null=True, blank=True)
    current_status = models.TextField(null=True, blank=True)
    current_status_code = models.IntegerField(null=True, blank=True)
    regime = models.TextField(null=True, blank=True)
    scope = models.TextField(null=True, blank=True)
    appreciation_mode = models.TextField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    originating_house = models.CharField(
        max_length=10, choices=House.choices, null=True, blank=True
    )
    raw_payload = models.JSONField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "propositions"
        constraints = [
            models.UniqueConstraint(fields=["house", "external_id"], name="propositions_house_external_id")
        ]
        indexes = [
            models.Index(fields=["house", "-year"], name="idx_prop_house_year"),
            models.Index(fields=["-presented_at"], name="idx_prop_presented"),
            models.Index(fields=["type_code", "-year"], name="idx_prop_type"),
        ]

    def __str__(self):
        return f"{self.number_label} ({self.year})"


class PropositionEvent(models.Model):
    proposition = models.ForeignKey(
        Proposition, on_delete=models.CASCADE, related_name="events"
    )
    event_at = models.DateTimeField()
    sequence = models.IntegerField(null=True, blank=True)
    description = models.TextField(null=True, blank=True)
    situation = models.TextField(null=True, blank=True)
    dispatch = models.TextField(null=True, blank=True)
    committee_id = models.BigIntegerField(null=True, blank=True)
    raw_payload = models.JSONField(null=True, blank=True)

    class Meta:
        db_table = "proposition_events"
        indexes = [
            models.Index(fields=["proposition", "-event_at"], name="idx_events_prop_date"),
            models.Index(fields=["-event_at"], name="idx_events_date"),
        ]


class PropositionAuthor(models.Model):
    proposition = models.ForeignKey(
        Proposition, on_delete=models.CASCADE, related_name="authors"
    )
    parliamentarian = models.ForeignKey(
        Parliamentarian, on_delete=models.SET_NULL, null=True, blank=True, related_name="authored_propositions"
    )
    institutional_author = models.ForeignKey(
        InstitutionalAuthor, on_delete=models.SET_NULL, null=True, blank=True, related_name="authored_propositions"
    )
    party = models.ForeignKey(
        Party, on_delete=models.SET_NULL, null=True, blank=True, related_name="authored_propositions"
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
    proposition = models.OneToOneField(
        Proposition, on_delete=models.CASCADE, primary_key=True, related_name="analysis"
    )
    classification = models.SmallIntegerField(null=True, blank=True)
    classification_probability = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    llm_position = models.SmallIntegerField(null=True, blank=True)
    final_position_score = models.DecimalField(max_digits=5, decimal_places=4, null=True, blank=True)
    expert_opinion = models.TextField(null=True, blank=True)
    expert_id = models.BigIntegerField(null=True, blank=True)
    ai_summary = models.TextField(null=True, blank=True)
    quiterometer_score = models.FloatField(null=True, blank=True)
    analyzed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "proposition_analysis"
        indexes = [
            models.Index(fields=["quiterometer_score"], name="idx_analysis_quitero"),
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
    # Tema (class humana): texto livre, preserva fidelidade ao dado original
    human_theme = models.TextField(null=True, blank=True)
    comments = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "proposition_annotations"

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
