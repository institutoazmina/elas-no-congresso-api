from django.db import models

from apps.core.enums import CaucusKind, CommitteeStage, House
from apps.legislatures.models import Legislature, Parliamentarian
from apps.propositions.models import Proposition


class Committee(models.Model):
    house = models.CharField(max_length=10, choices=House.choices)
    acronym = models.TextField()
    name = models.TextField()
    kind = models.TextField()
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "committees"
        constraints = [
            models.UniqueConstraint(fields=["house", "acronym"], name="committees_house_acronym")
        ]
        indexes = [models.Index(fields=["house", "is_active"], name="idx_committee_house")]

    def __str__(self):
        return f"{self.acronym} ({self.house})"


class CommitteeMembership(models.Model):
    committee = models.ForeignKey(Committee, on_delete=models.CASCADE, related_name="memberships")
    parliamentarian = models.ForeignKey(
        Parliamentarian, on_delete=models.CASCADE, related_name="committee_memberships"
    )
    role = models.TextField()
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "committee_memberships"
        indexes = [
            models.Index(fields=["parliamentarian"], name="idx_cm_parl"),
            models.Index(fields=["committee"], name="idx_cm_committee"),
        ]

    @property
    def is_current(self):
        return self.end_date is None


class CommitteePresidency(models.Model):
    committee = models.ForeignKey(Committee, on_delete=models.CASCADE, related_name="presidencies")
    parliamentarian = models.ForeignKey(
        Parliamentarian, on_delete=models.CASCADE, related_name="committee_presidencies"
    )
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "committee_presidencies"
        # EXCLUDE constraint created via RunSQL in migration (requires btree_gist)


class PropositionCommittee(models.Model):
    proposition = models.ForeignKey(
        Proposition, on_delete=models.CASCADE, related_name="proposition_committees"
    )
    committee = models.ForeignKey(Committee, on_delete=models.RESTRICT, related_name="proposition_committees")
    stage = models.CharField(max_length=10, choices=CommitteeStage.choices)
    entered_at = models.DateField(null=True, blank=True)
    exited_at = models.DateField(null=True, blank=True)
    result = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "proposition_committees"
        constraints = [
            models.UniqueConstraint(
                fields=["proposition", "committee", "entered_at"],
                name="proposition_committees_unique",
            )
        ]
        indexes = [
            models.Index(fields=["proposition"], name="idx_pc_prop"),
            models.Index(fields=["committee", "stage"], name="idx_pc_committee_stage"),
        ]


class Caucus(models.Model):
    kind = models.CharField(max_length=10, choices=CaucusKind.choices)
    name = models.TextField()
    legislature = models.ForeignKey(
        Legislature, on_delete=models.SET_NULL, null=True, blank=True, related_name="caucuses"
    )
    description = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "caucuses"
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "name", "legislature"],
                name="caucuses_kind_name_legislature",
            )
        ]

    def __str__(self):
        return self.name


class CaucusMembership(models.Model):
    caucus = models.ForeignKey(Caucus, on_delete=models.CASCADE, related_name="memberships")
    parliamentarian = models.ForeignKey(
        Parliamentarian, on_delete=models.CASCADE, related_name="caucus_memberships"
    )
    role = models.TextField(null=True, blank=True)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "caucus_memberships"
        indexes = [models.Index(fields=["parliamentarian"], name="idx_caucus_parl")]
