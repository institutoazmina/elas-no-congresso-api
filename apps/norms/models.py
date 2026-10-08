from django.db import models

from apps.core.enums import AmendRelationType, LegalNormType
from apps.propositions.models import Proposition


class LegalNorm(models.Model):
    type = models.CharField(verbose_name="Tipo", max_length=30, choices=LegalNormType.choices)
    number = models.IntegerField(verbose_name="Número", null=True, blank=True)
    year = models.SmallIntegerField(verbose_name="Ano", null=True, blank=True)
    published_at = models.DateField(verbose_name="Publicado em", null=True, blank=True)
    official_name = models.TextField(verbose_name="Nome oficial")
    popular_name = models.TextField(verbose_name="Nome popular", null=True, blank=True)

    class Meta:
        verbose_name = "Norma legal"
        verbose_name_plural = "Normas legais"
        db_table = "legal_norms"
        constraints = [
            models.UniqueConstraint(
                fields=["type", "number", "year"], name="legal_norms_type_number_year"
            )
        ]
        indexes = [
            models.Index(
                fields=["popular_name"],
                name="idx_norms_popular",
                condition=models.Q(popular_name__isnull=False),
            ),
        ]

    def __str__(self):
        return self.popular_name or self.official_name


class PropositionAmend(models.Model):
    proposition = models.ForeignKey(
        Proposition, verbose_name="Proposição", on_delete=models.CASCADE, related_name="amends"
    )
    norm = models.ForeignKey(
        LegalNorm, verbose_name="Norma legal", on_delete=models.CASCADE, related_name="amends"
    )
    relation_type = models.CharField(
        verbose_name="Tipo de relação",
        max_length=15,
        choices=AmendRelationType.choices,
        default=AmendRelationType.ALTERA,
    )
    extracted_from = models.TextField(verbose_name="Extraído de", null=True, blank=True)

    class Meta:
        verbose_name = "Alteração de norma"
        verbose_name_plural = "Alterações de normas"
        db_table = "proposition_amends"
        constraints = [
            models.UniqueConstraint(
                fields=["proposition", "norm", "relation_type"], name="proposition_amends_pk"
            )
        ]
        indexes = [models.Index(fields=["norm", "relation_type"], name="idx_amends_norm")]
