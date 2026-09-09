from django.db import models

from apps.core.enums import CaucusKind, CommitteeStage, House
from apps.legislatures.models import Legislature, Parliamentarian
from apps.propositions.models import Proposition


class ProvenanceFields(models.Model):
    source = models.TextField(null=True, blank=True)
    source_key = models.TextField(null=True, blank=True)
    source_url = models.TextField(null=True, blank=True)
    first_seen_at = models.DateTimeField(null=True, blank=True)
    last_seen_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True


class Committee(ProvenanceFields):
    house = models.CharField(max_length=10, choices=House.choices)
    acronym = models.TextField()
    name = models.TextField()
    kind = models.TextField()
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "committees"
        constraints = [
            models.UniqueConstraint(fields=["house", "acronym"], name="committees_house_acronym"),
            models.UniqueConstraint(
                fields=["source", "source_key"],
                condition=models.Q(source__isnull=False, source_key__isnull=False),
                name="committee_source_key_unique",
            ),
        ]
        indexes = [models.Index(fields=["house", "is_active"], name="idx_committee_house")]

    def __str__(self):
        return f"{self.acronym} ({self.house})"


class CommitteeMembership(ProvenanceFields):
    committee = models.ForeignKey(Committee, on_delete=models.CASCADE, related_name="memberships")
    parliamentarian = models.ForeignKey(
        Parliamentarian, on_delete=models.CASCADE, related_name="committee_memberships"
    )
    legislature = models.ForeignKey(
        Legislature,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="committee_memberships",
    )
    role = models.TextField()
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_observed_current = models.BooleanField(null=True, blank=True)

    class Meta:
        db_table = "committee_memberships"
        indexes = [
            models.Index(fields=["parliamentarian"], name="idx_cm_parl"),
            models.Index(fields=["committee"], name="idx_cm_committee"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "source_key"],
                condition=models.Q(source__isnull=False, source_key__isnull=False),
                name="cm_source_key_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(start_date__isnull=True)
                | models.Q(end_date__isnull=True)
                | models.Q(end_date__gte=models.F("start_date")),
                name="cm_date_range",
            ),
        ]

    @property
    def is_current(self):
        return self.end_date is None


class CommitteePresidency(ProvenanceFields):
    committee = models.ForeignKey(Committee, on_delete=models.CASCADE, related_name="presidencies")
    parliamentarian = models.ForeignKey(
        Parliamentarian, on_delete=models.CASCADE, related_name="committee_presidencies"
    )
    legislature = models.ForeignKey(
        Legislature,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="committee_presidencies",
    )
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_observed_current = models.BooleanField(null=True, blank=True)

    class Meta:
        db_table = "committee_presidencies"
        constraints = [
            models.UniqueConstraint(
                fields=["source", "source_key"],
                condition=models.Q(source__isnull=False, source_key__isnull=False),
                name="cp_source_key_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(start_date__isnull=True)
                | models.Q(end_date__isnull=True)
                | models.Q(end_date__gte=models.F("start_date")),
                name="cp_date_range",
            ),
        ]


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


class Caucus(ProvenanceFields):
    house = models.CharField(max_length=10, choices=House.choices, null=True, blank=True)
    kind = models.CharField(max_length=10, choices=CaucusKind.choices)
    name = models.TextField()
    legislature = models.ForeignKey(
        Legislature, on_delete=models.SET_NULL, null=True, blank=True, related_name="caucuses"
    )
    description = models.TextField(null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(null=True, blank=True)

    class Meta:
        db_table = "caucuses"
        constraints = [
            models.UniqueConstraint(
                fields=["kind", "name", "legislature"],
                name="caucuses_kind_name_legislature",
            ),
            models.UniqueConstraint(
                fields=["source", "source_key"],
                condition=models.Q(source__isnull=False, source_key__isnull=False),
                name="caucus_source_key_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(start_date__isnull=True)
                | models.Q(end_date__isnull=True)
                | models.Q(end_date__gte=models.F("start_date")),
                name="caucus_date_range",
            ),
        ]

    def __str__(self):
        return self.name


class CaucusMembership(ProvenanceFields):
    caucus = models.ForeignKey(Caucus, on_delete=models.CASCADE, related_name="memberships")
    parliamentarian = models.ForeignKey(
        Parliamentarian, on_delete=models.CASCADE, related_name="caucus_memberships"
    )
    role = models.TextField(null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_observed_current = models.BooleanField(null=True, blank=True)

    class Meta:
        db_table = "caucus_memberships"
        indexes = [models.Index(fields=["parliamentarian"], name="idx_caucus_parl")]
        constraints = [
            models.UniqueConstraint(
                fields=["source", "source_key"],
                condition=models.Q(source__isnull=False, source_key__isnull=False),
                name="cau_mem_source_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(start_date__isnull=True)
                | models.Q(end_date__isnull=True)
                | models.Q(end_date__gte=models.F("start_date")),
                name="cau_mem_date_range",
            ),
        ]
