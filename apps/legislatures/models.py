from django.db import models

from apps.core.enums import ContactChannel, Gender, House


class Legislature(models.Model):
    number = models.SmallIntegerField(primary_key=True)
    start_date = models.DateField()
    end_date = models.DateField()

    class Meta:
        db_table = "legislatures"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__gt=models.F("start_date")),
                name="legislatures_end_after_start",
            )
        ]

    @classmethod
    def for_date(cls, date):
        """Legislatura vigente na data, ou None — há lacunas entre legislaturas
        (dissoluções, Governo Provisório 1930-33, Estado Novo 1937-46)."""
        return cls.objects.filter(start_date__lte=date, end_date__gte=date).first()

    def __str__(self):
        return f"{self.number}ª Legislatura"


class Party(models.Model):
    acronym = models.TextField(unique=True)
    name = models.TextField()
    ideology = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "parties"
        verbose_name_plural = "parties"

    def __str__(self):
        return self.acronym


class Parliamentarian(models.Model):
    full_name = models.TextField()
    social_name = models.TextField(null=True, blank=True)
    photo_url = models.TextField(null=True, blank=True)
    gender = models.CharField(max_length=2, choices=Gender.choices, null=True, blank=True)
    birth_date = models.DateField(null=True, blank=True)
    race = models.TextField(null=True, blank=True)
    education = models.TextField(null=True, blank=True)
    birthplace = models.TextField(null=True, blank=True)
    profession = models.TextField(null=True, blank=True)
    religion = models.TextField(null=True, blank=True)
    bio = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "parliamentarians"

    def __str__(self):
        return self.social_name or self.full_name


class ParliamentarianProfileSource(models.Model):
    """The latest normalized profile observed at one external source."""

    parliamentarian = models.ForeignKey(
        Parliamentarian, on_delete=models.CASCADE, related_name="profile_sources"
    )
    source = models.TextField()
    source_key = models.TextField()
    profile_values = models.JSONField(default=dict)
    metadata = models.JSONField(default=dict, blank=True)
    source_url = models.TextField(null=True, blank=True)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "parliamentarian_profile_sources"
        constraints = [
            models.UniqueConstraint(
                fields=["source", "source_key"],
                name="parliamentarian_profile_sources_source_key_unique",
            )
        ]
        indexes = [
            models.Index(
                fields=["parliamentarian", "source"],
                name="idx_prof_src_parl_source",
            )
        ]


# Both names are useful at call sites; keep one concrete Django model/table.
ParliamentarianSourceProfile = ParliamentarianProfileSource
SourceProfile = ParliamentarianProfileSource


class ParliamentarianTerm(models.Model):
    parliamentarian = models.ForeignKey(
        Parliamentarian, on_delete=models.CASCADE, related_name="terms"
    )
    legislature_number = models.ForeignKey(
        Legislature, on_delete=models.RESTRICT, db_column="legislature_number", related_name="terms"
    )
    party = models.ForeignKey(Party, on_delete=models.RESTRICT, related_name="terms")
    house = models.CharField(max_length=10, choices=House.choices)
    role = models.TextField()
    state = models.CharField(max_length=2)
    external_id = models.BigIntegerField()
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)

    class Meta:
        db_table = "parliamentarian_terms"
        constraints = [
            models.UniqueConstraint(
                fields=["house", "external_id", "legislature_number_id"],
                name="parliamentarian_terms_house_external_id_legislature",
            )
        ]
        indexes = [
            models.Index(fields=["parliamentarian"], name="idx_term_parliamentarian"),
            models.Index(fields=["legislature_number"], name="idx_term_legislature"),
        ]

    @property
    def is_current(self):
        return self.end_date is None

    def __str__(self):
        return f"{self.parliamentarian} — {self.house}/{self.state}"


class ParliamentarianPost(models.Model):
    parliamentarian = models.ForeignKey(
        Parliamentarian, on_delete=models.CASCADE, related_name="posts"
    )
    house = models.CharField(max_length=10, choices=House.choices)
    legislature = models.ForeignKey(
        Legislature,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="parliamentarian_posts",
    )
    title = models.TextField()
    organization_name = models.TextField(null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_observed_current = models.BooleanField(null=True, blank=True)
    source = models.TextField()
    source_key = models.TextField()
    source_url = models.TextField(null=True, blank=True)
    first_seen_at = models.DateTimeField(auto_now_add=True)
    last_seen_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "parliamentarian_posts"
        constraints = [
            models.UniqueConstraint(
                fields=["source", "source_key"],
                name="parl_posts_source_unique",
            ),
            models.CheckConstraint(
                condition=models.Q(start_date__isnull=True)
                | models.Q(end_date__isnull=True)
                | models.Q(end_date__gte=models.F("start_date")),
                name="parliamentarian_posts_date_range",
            ),
        ]
        indexes = [
            models.Index(
                fields=["parliamentarian", "legislature", "start_date"],
                name="idx_post_parl_leg_start",
            ),
            models.Index(
                fields=["house", "legislature", "is_observed_current"],
                name="idx_post_house_leg_obs",
            ),
        ]


class ParliamentarianContact(models.Model):
    parliamentarian = models.ForeignKey(
        Parliamentarian, on_delete=models.CASCADE, related_name="contacts"
    )
    channel = models.CharField(max_length=20, choices=ContactChannel.choices)
    value = models.TextField()
    is_public = models.BooleanField(default=True)

    class Meta:
        db_table = "parliamentarian_contacts"
        constraints = [
            models.UniqueConstraint(
                fields=["parliamentarian", "channel", "value"],
                name="parliamentarian_contacts_unique",
            )
        ]


class ParliamentarianAsset(models.Model):
    parliamentarian = models.ForeignKey(
        Parliamentarian, on_delete=models.CASCADE, related_name="assets"
    )
    reference_year = models.SmallIntegerField()
    total_value = models.DecimalField(max_digits=14, decimal_places=2)
    breakdown = models.JSONField(null=True, blank=True)
    source = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "parliamentarian_assets"
        constraints = [
            models.UniqueConstraint(
                fields=["parliamentarian", "reference_year"],
                name="parliamentarian_assets_unique_year",
            )
        ]


class ParliamentarianExpense(models.Model):
    parliamentarian = models.ForeignKey(
        Parliamentarian, on_delete=models.CASCADE, related_name="expenses"
    )
    reference_month = models.DateField()
    category = models.TextField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    supplier = models.TextField(null=True, blank=True)
    document_url = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "parliamentarian_expenses"
        indexes = [
            models.Index(
                fields=["parliamentarian", "-reference_month"],
                name="idx_expenses_parl_month",
            )
        ]


class ParliamentarianCampaignFinance(models.Model):
    parliamentarian = models.ForeignKey(
        Parliamentarian, on_delete=models.CASCADE, related_name="campaign_finances"
    )
    election_year = models.SmallIntegerField()
    kind = models.TextField()
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    counterparty = models.TextField(null=True, blank=True)
    counterparty_cnpj_cpf = models.TextField(null=True, blank=True)
    description = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "parliamentarian_campaign_finance"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(kind__in=["expense", "donation"]),
                name="campaign_finance_kind_check",
            )
        ]
        indexes = [
            models.Index(
                fields=["parliamentarian", "-election_year"],
                name="idx_campaign_parl_year",
            )
        ]


class ParliamentarianInvestigation(models.Model):
    parliamentarian = models.ForeignKey(
        Parliamentarian, on_delete=models.CASCADE, related_name="investigations"
    )
    case_number = models.TextField(null=True, blank=True)
    court = models.TextField(null=True, blank=True)
    status = models.TextField()
    subject = models.TextField()
    started_at = models.DateField(null=True, blank=True)
    source_url = models.TextField(null=True, blank=True)

    class Meta:
        db_table = "parliamentarian_investigations"


class ParliamentarianOffice(models.Model):
    parliamentarian = models.OneToOneField(
        Parliamentarian,
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="office",
    )
    reference_date = models.DateField()
    staff_count = models.IntegerField(null=True, blank=True)
    gross_salary = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    has_official_housing = models.BooleanField(null=True, blank=True)
    housing_allowance = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    class Meta:
        db_table = "parliamentarian_office"


class ParliamentarianHousingHistory(models.Model):
    parliamentarian = models.ForeignKey(
        Parliamentarian, on_delete=models.CASCADE, related_name="housing_history"
    )
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    has_official_housing = models.BooleanField()
    housing_allowance = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)

    class Meta:
        db_table = "parliamentarian_housing_history"
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__isnull=True)
                | models.Q(end_date__gt=models.F("start_date")),
                name="housing_end_after_start",
            )
        ]
        indexes = [
            models.Index(
                fields=["parliamentarian", "-start_date"],
                name="idx_housing_parl",
            )
        ]


class InstitutionalAuthor(models.Model):
    name = models.TextField(unique=True)
    kind = models.TextField()

    class Meta:
        db_table = "institutional_authors"

    def __str__(self):
        return self.name
