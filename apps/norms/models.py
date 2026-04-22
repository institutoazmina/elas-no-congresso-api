from django.db import models

from apps.core.enums import AmendRelationType, LegalNormType
from apps.propositions.models import Proposition


class LegalNorm(models.Model):
    type = models.CharField(max_length=30, choices=LegalNormType.choices)
    number = models.IntegerField(null=True, blank=True)
    year = models.SmallIntegerField(null=True, blank=True)
    published_at = models.DateField(null=True, blank=True)
    official_name = models.TextField()
    popular_name = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "legal_norms"
        constraints = [
            models.UniqueConstraint(fields=["type", "number", "year"], name="legal_norms_type_number_year")
        ]
        indexes = [
            models.Index(
                fields=["popular_name"], name="idx_norms_popular",
                condition=models.Q(popular_name__isnull=False),
            ),
        ]

    def __str__(self):
        return self.popular_name or self.official_name


class PropositionAmend(models.Model):
    proposition = models.ForeignKey(
        Proposition, on_delete=models.CASCADE, related_name="amends"
    )
    norm = models.ForeignKey(LegalNorm, on_delete=models.CASCADE, related_name="amends")
    relation_type = models.CharField(
        max_length=15, choices=AmendRelationType.choices, default=AmendRelationType.ALTERA
    )
    extracted_from = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "proposition_amends"
        constraints = [
            models.UniqueConstraint(
                fields=["proposition", "norm", "relation_type"], name="proposition_amends_pk"
            )
        ]
        indexes = [models.Index(fields=["norm", "relation_type"], name="idx_amends_norm")]
