from django.db import models

from apps.core.enums import RelationType
from apps.propositions.models import Proposition


class Theme(models.Model):
    slug = models.TextField(verbose_name="Identificador textual", unique=True)
    name = models.TextField(verbose_name="Nome")
    parent = models.ForeignKey(
        "self",
        verbose_name="Tema superior",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
    )

    class Meta:
        verbose_name = "Tema"
        verbose_name_plural = "Temas"
        db_table = "themes"
        indexes = [models.Index(fields=["parent"], name="idx_themes_parent")]

    def __str__(self):
        return self.name


class AnalyticalTag(models.Model):
    slug = models.TextField(verbose_name="Identificador textual", unique=True)
    name = models.TextField(verbose_name="Nome")
    description = models.TextField(verbose_name="Descrição", null=True, blank=True)

    class Meta:
        verbose_name = "Etiqueta analítica"
        verbose_name_plural = "Etiquetas analíticas"
        db_table = "analytical_tags"

    def __str__(self):
        return self.name


class PropositionTheme(models.Model):
    proposition = models.ForeignKey(
        Proposition,
        verbose_name="Proposição",
        on_delete=models.CASCADE,
        related_name="proposition_themes",
    )
    theme = models.ForeignKey(
        Theme, verbose_name="Tema", on_delete=models.CASCADE, related_name="proposition_themes"
    )
    rank = models.SmallIntegerField(verbose_name="Ordem", default=1)

    class Meta:
        verbose_name = "Tema de proposição"
        verbose_name_plural = "Temas de proposições"
        db_table = "proposition_themes"
        constraints = [
            models.UniqueConstraint(fields=["proposition", "theme"], name="proposition_themes_pk")
        ]
        indexes = [models.Index(fields=["theme", "proposition"], name="idx_pt_theme")]


class PropositionTag(models.Model):
    proposition = models.ForeignKey(
        Proposition,
        verbose_name="Proposição",
        on_delete=models.CASCADE,
        related_name="proposition_tags",
    )
    tag = models.ForeignKey(
        AnalyticalTag,
        verbose_name="Etiqueta",
        on_delete=models.CASCADE,
        related_name="proposition_tags",
    )

    class Meta:
        verbose_name = "Etiqueta de proposição"
        verbose_name_plural = "Etiquetas de proposições"
        db_table = "proposition_tags"
        constraints = [
            models.UniqueConstraint(fields=["proposition", "tag"], name="proposition_tags_pk")
        ]
        indexes = [models.Index(fields=["tag", "proposition"], name="idx_ptag_tag")]


class PropositionRelation(models.Model):
    proposition = models.ForeignKey(
        Proposition,
        verbose_name="Proposição",
        on_delete=models.CASCADE,
        related_name="relations_from",
    )
    related_proposition = models.ForeignKey(
        Proposition,
        verbose_name="Proposição relacionada",
        on_delete=models.CASCADE,
        related_name="relations_to",
    )
    relation_type = models.CharField(
        verbose_name="Tipo de relação", max_length=20, choices=RelationType.choices
    )
    similarity_score = models.FloatField(
        verbose_name="Pontuação de similaridade", null=True, blank=True
    )
    created_at = models.DateTimeField(verbose_name="Criado em", auto_now_add=True)

    class Meta:
        verbose_name = "Relação entre proposições"
        verbose_name_plural = "Relações entre proposições"
        db_table = "proposition_relations"
        constraints = [
            models.UniqueConstraint(
                fields=["proposition", "related_proposition", "relation_type"],
                name="proposition_relations_pk",
            ),
            models.CheckConstraint(
                condition=~models.Q(proposition=models.F("related_proposition")),
                name="proposition_relations_no_self",
            ),
            models.CheckConstraint(
                condition=models.Q(relation_type__in=RelationType.values),
                name="proposition_relations_type_check",
            ),
        ]
        indexes = [
            models.Index(
                fields=["related_proposition", "relation_type"], name="idx_relations_related"
            )
        ]
