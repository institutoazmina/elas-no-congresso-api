from django.db import models

from apps.core.enums import CaucusKind, CommitteeStage, House
from apps.legislatures.models import Legislature, Parliamentarian
from apps.propositions.models import Proposition


class ProvenanceFields(models.Model):
    source = models.TextField(verbose_name="Fonte", null=True, blank=True)
    source_key = models.TextField(verbose_name="Identificador na fonte", null=True, blank=True)
    source_url = models.TextField(verbose_name="URL da fonte", null=True, blank=True)
    first_seen_at = models.DateTimeField(
        verbose_name="Primeira observação em", null=True, blank=True
    )
    last_seen_at = models.DateTimeField(verbose_name="Última observação em", null=True, blank=True)

    class Meta:
        abstract = True


class Committee(ProvenanceFields):
    house = models.CharField(verbose_name="Casa legislativa", max_length=10, choices=House.choices)
    acronym = models.TextField(verbose_name="Sigla")
    name = models.TextField(verbose_name="Nome")
    kind = models.TextField(verbose_name="Tipo")
    is_active = models.BooleanField(verbose_name="Ativo", default=True)

    class Meta:
        verbose_name = "Comissão"
        verbose_name_plural = "Comissões"
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
    committee = models.ForeignKey(
        Committee, verbose_name="Comissão", on_delete=models.CASCADE, related_name="memberships"
    )
    parliamentarian = models.ForeignKey(
        Parliamentarian,
        verbose_name="Parlamentar",
        on_delete=models.CASCADE,
        related_name="committee_memberships",
    )
    legislature = models.ForeignKey(
        Legislature,
        verbose_name="Legislatura",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="committee_memberships",
    )
    role = models.TextField(verbose_name="Função")
    start_date = models.DateField(verbose_name="Data de início", null=True, blank=True)
    end_date = models.DateField(verbose_name="Data de término", null=True, blank=True)
    is_observed_current = models.BooleanField(
        verbose_name="Vigente na fonte", null=True, blank=True
    )

    class Meta:
        verbose_name = "Participação em comissão"
        verbose_name_plural = "Participações em comissões"
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
    committee = models.ForeignKey(
        Committee, verbose_name="Comissão", on_delete=models.CASCADE, related_name="presidencies"
    )
    parliamentarian = models.ForeignKey(
        Parliamentarian,
        verbose_name="Parlamentar",
        on_delete=models.CASCADE,
        related_name="committee_presidencies",
    )
    legislature = models.ForeignKey(
        Legislature,
        verbose_name="Legislatura",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="committee_presidencies",
    )
    start_date = models.DateField(verbose_name="Data de início", null=True, blank=True)
    end_date = models.DateField(verbose_name="Data de término", null=True, blank=True)
    is_observed_current = models.BooleanField(
        verbose_name="Vigente na fonte", null=True, blank=True
    )

    class Meta:
        verbose_name = "Presidência de comissão"
        verbose_name_plural = "Presidências de comissões"
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
        Proposition,
        verbose_name="Proposição",
        on_delete=models.CASCADE,
        related_name="proposition_committees",
    )
    committee = models.ForeignKey(
        Committee,
        verbose_name="Comissão",
        on_delete=models.RESTRICT,
        related_name="proposition_committees",
    )
    stage = models.CharField(verbose_name="Etapa", max_length=10, choices=CommitteeStage.choices)
    entered_at = models.DateField(verbose_name="Data de entrada", null=True, blank=True)
    exited_at = models.DateField(verbose_name="Data de saída", null=True, blank=True)
    result = models.TextField(verbose_name="Resultado", null=True, blank=True)

    class Meta:
        verbose_name = "Tramitação em comissão"
        verbose_name_plural = "Tramitações em comissões"
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
    house = models.CharField(
        verbose_name="Casa legislativa", max_length=10, choices=House.choices, null=True, blank=True
    )
    kind = models.CharField(verbose_name="Tipo", max_length=10, choices=CaucusKind.choices)
    name = models.TextField(verbose_name="Nome")
    legislature = models.ForeignKey(
        Legislature,
        verbose_name="Legislatura",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="caucuses",
    )
    description = models.TextField(verbose_name="Descrição", null=True, blank=True)
    start_date = models.DateField(verbose_name="Data de início", null=True, blank=True)
    end_date = models.DateField(verbose_name="Data de término", null=True, blank=True)
    is_active = models.BooleanField(verbose_name="Ativo", null=True, blank=True)

    class Meta:
        verbose_name = "Frente ou bancada"
        verbose_name_plural = "Frentes e bancadas"
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
    caucus = models.ForeignKey(
        Caucus,
        verbose_name="Frente ou bancada",
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    parliamentarian = models.ForeignKey(
        Parliamentarian,
        verbose_name="Parlamentar",
        on_delete=models.CASCADE,
        related_name="caucus_memberships",
    )
    role = models.TextField(verbose_name="Função", null=True, blank=True)
    start_date = models.DateField(verbose_name="Data de início", null=True, blank=True)
    end_date = models.DateField(verbose_name="Data de término", null=True, blank=True)
    is_observed_current = models.BooleanField(
        verbose_name="Vigente na fonte", null=True, blank=True
    )

    class Meta:
        verbose_name = "Participação em frente ou bancada"
        verbose_name_plural = "Participações em frentes e bancadas"
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
