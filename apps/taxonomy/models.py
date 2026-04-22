from django.db import models

from apps.propositions.models import Proposition


class Theme(models.Model):
    slug = models.TextField(unique=True)
    name = models.TextField()
    parent = models.ForeignKey(
        "self", on_delete=models.SET_NULL, null=True, blank=True, related_name="children"
    )

    class Meta:
        db_table = "themes"
        indexes = [models.Index(fields=["parent"], name="idx_themes_parent")]

    def __str__(self):
        return self.name


class AnalyticalTag(models.Model):
    slug = models.TextField(unique=True)
    name = models.TextField()
    description = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "analytical_tags"

    def __str__(self):
        return self.name


class PropositionTheme(models.Model):
    proposition = models.ForeignKey(
        Proposition, on_delete=models.CASCADE, related_name="proposition_themes"
    )
    theme = models.ForeignKey(Theme, on_delete=models.CASCADE, related_name="proposition_themes")
    rank = models.SmallIntegerField(default=1)

    class Meta:
        db_table = "proposition_themes"
        constraints = [
            models.UniqueConstraint(fields=["proposition", "theme"], name="proposition_themes_pk")
        ]
        indexes = [models.Index(fields=["theme", "proposition"], name="idx_pt_theme")]


class PropositionTag(models.Model):
    proposition = models.ForeignKey(
        Proposition, on_delete=models.CASCADE, related_name="proposition_tags"
    )
    tag = models.ForeignKey(AnalyticalTag, on_delete=models.CASCADE, related_name="proposition_tags")

    class Meta:
        db_table = "proposition_tags"
        constraints = [
            models.UniqueConstraint(fields=["proposition", "tag"], name="proposition_tags_pk")
        ]
        indexes = [models.Index(fields=["tag", "proposition"], name="idx_ptag_tag")]


class PropositionRelation(models.Model):
    proposition = models.ForeignKey(
        Proposition, on_delete=models.CASCADE, related_name="relations_from"
    )
    related_proposition = models.ForeignKey(
        Proposition, on_delete=models.CASCADE, related_name="relations_to"
    )
    relation_type = models.CharField(max_length=20)
    similarity_score = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
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
                condition=models.Q(relation_type__in=["appended", "similar", "predecessor", "successor"]),
                name="proposition_relations_type_check",
            ),
        ]
        indexes = [
            models.Index(fields=["related_proposition", "relation_type"], name="idx_relations_related")
        ]
