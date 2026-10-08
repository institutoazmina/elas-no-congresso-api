from django.db import models

from apps.core.enums import ContactChannel, Gender, House


class Legislature(models.Model):
    number = models.SmallIntegerField(verbose_name="Número", primary_key=True)
    start_date = models.DateField(verbose_name="Data de início")
    end_date = models.DateField(verbose_name="Data de término")

    class Meta:
        verbose_name = "Legislatura"
        verbose_name_plural = "Legislaturas"
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
    acronym = models.TextField(verbose_name="Sigla", unique=True)
    name = models.TextField(verbose_name="Nome")
    ideology = models.TextField(verbose_name="Ideologia", null=True, blank=True)
    created_at = models.DateTimeField(verbose_name="Criado em", auto_now_add=True)

    class Meta:
        verbose_name = "Partido"
        verbose_name_plural = "Partidos"
        db_table = "parties"

    def __str__(self):
        return self.acronym


class Parliamentarian(models.Model):
    full_name = models.TextField(verbose_name="Nome completo")
    social_name = models.TextField(verbose_name="Nome social", null=True, blank=True)
    photo_url = models.TextField(verbose_name="URL da foto", null=True, blank=True)
    gender = models.CharField(
        verbose_name="Gênero", max_length=2, choices=Gender.choices, null=True, blank=True
    )
    birth_date = models.DateField(verbose_name="Data de nascimento", null=True, blank=True)
    race = models.TextField(verbose_name="Raça ou cor", null=True, blank=True)
    education = models.TextField(verbose_name="Escolaridade", null=True, blank=True)
    birthplace = models.TextField(verbose_name="Naturalidade", null=True, blank=True)
    profession = models.TextField(verbose_name="Profissão", null=True, blank=True)
    religion = models.TextField(verbose_name="Religião", null=True, blank=True)
    bio = models.TextField(verbose_name="Biografia", null=True, blank=True)
    created_at = models.DateTimeField(verbose_name="Criado em", auto_now_add=True)
    updated_at = models.DateTimeField(verbose_name="Atualizado em", auto_now=True)

    class Meta:
        verbose_name = "Parlamentar"
        verbose_name_plural = "Parlamentares"
        db_table = "parliamentarians"

    def __str__(self):
        return self.social_name or self.full_name


class ParliamentarianProfileSource(models.Model):
    """The latest normalized profile observed at one external source."""

    parliamentarian = models.ForeignKey(
        Parliamentarian,
        verbose_name="Parlamentar",
        on_delete=models.CASCADE,
        related_name="profile_sources",
    )
    source = models.TextField(verbose_name="Fonte")
    source_key = models.TextField(verbose_name="Identificador na fonte")
    profile_values = models.JSONField(verbose_name="Dados do perfil", default=dict)
    metadata = models.JSONField(verbose_name="Metadados", default=dict, blank=True)
    source_url = models.TextField(verbose_name="URL da fonte", null=True, blank=True)
    first_seen_at = models.DateTimeField(verbose_name="Primeira observação em", auto_now_add=True)
    last_seen_at = models.DateTimeField(verbose_name="Última observação em", auto_now=True)

    class Meta:
        verbose_name = "Fonte de perfil parlamentar"
        verbose_name_plural = "Fontes de perfis parlamentares"
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
        Parliamentarian, verbose_name="Parlamentar", on_delete=models.CASCADE, related_name="terms"
    )
    legislature_number = models.ForeignKey(
        Legislature,
        verbose_name="Legislatura",
        on_delete=models.RESTRICT,
        db_column="legislature_number",
        related_name="terms",
    )
    party = models.ForeignKey(
        Party, verbose_name="Partido", on_delete=models.RESTRICT, related_name="terms"
    )
    house = models.CharField(verbose_name="Casa legislativa", max_length=10, choices=House.choices)
    role = models.TextField(verbose_name="Função")
    state = models.CharField(verbose_name="UF", max_length=2)
    external_id = models.BigIntegerField(verbose_name="Identificador externo")
    start_date = models.DateField(verbose_name="Data de início")
    end_date = models.DateField(verbose_name="Data de término", null=True, blank=True)

    class Meta:
        verbose_name = "Mandato parlamentar"
        verbose_name_plural = "Mandatos parlamentares"
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
        Parliamentarian, verbose_name="Parlamentar", on_delete=models.CASCADE, related_name="posts"
    )
    house = models.CharField(verbose_name="Casa legislativa", max_length=10, choices=House.choices)
    legislature = models.ForeignKey(
        Legislature,
        verbose_name="Legislatura",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="parliamentarian_posts",
    )
    title = models.TextField(verbose_name="Título")
    organization_name = models.TextField(verbose_name="Nome da organização", null=True, blank=True)
    start_date = models.DateField(verbose_name="Data de início", null=True, blank=True)
    end_date = models.DateField(verbose_name="Data de término", null=True, blank=True)
    is_observed_current = models.BooleanField(
        verbose_name="Vigente na fonte", null=True, blank=True
    )
    source = models.TextField(verbose_name="Fonte")
    source_key = models.TextField(verbose_name="Identificador na fonte")
    source_url = models.TextField(verbose_name="URL da fonte", null=True, blank=True)
    first_seen_at = models.DateTimeField(verbose_name="Primeira observação em", auto_now_add=True)
    last_seen_at = models.DateTimeField(verbose_name="Última observação em", auto_now=True)

    class Meta:
        verbose_name = "Cargo parlamentar"
        verbose_name_plural = "Cargos parlamentares"
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
        Parliamentarian,
        verbose_name="Parlamentar",
        on_delete=models.CASCADE,
        related_name="contacts",
    )
    channel = models.CharField(verbose_name="Canal", max_length=20, choices=ContactChannel.choices)
    value = models.TextField(verbose_name="Valor")
    is_public = models.BooleanField(verbose_name="Público", default=True)

    class Meta:
        verbose_name = "Contato parlamentar"
        verbose_name_plural = "Contatos parlamentares"
        db_table = "parliamentarian_contacts"
        constraints = [
            models.UniqueConstraint(
                fields=["parliamentarian", "channel", "value"],
                name="parliamentarian_contacts_unique",
            )
        ]


class ParliamentarianAsset(models.Model):
    parliamentarian = models.ForeignKey(
        Parliamentarian, verbose_name="Parlamentar", on_delete=models.CASCADE, related_name="assets"
    )
    reference_year = models.SmallIntegerField(verbose_name="Ano de referência")
    total_value = models.DecimalField(verbose_name="Valor total", max_digits=14, decimal_places=2)
    breakdown = models.JSONField(verbose_name="Detalhamento", null=True, blank=True)
    source = models.TextField(verbose_name="Fonte", null=True, blank=True)

    class Meta:
        verbose_name = "Patrimônio parlamentar"
        verbose_name_plural = "Patrimônios parlamentares"
        db_table = "parliamentarian_assets"
        constraints = [
            models.UniqueConstraint(
                fields=["parliamentarian", "reference_year"],
                name="parliamentarian_assets_unique_year",
            )
        ]


class ParliamentarianExpense(models.Model):
    parliamentarian = models.ForeignKey(
        Parliamentarian,
        verbose_name="Parlamentar",
        on_delete=models.CASCADE,
        related_name="expenses",
    )
    reference_month = models.DateField(verbose_name="Mês de referência")
    category = models.TextField(verbose_name="Categoria")
    amount = models.DecimalField(verbose_name="Valor", max_digits=12, decimal_places=2)
    supplier = models.TextField(verbose_name="Fornecedor", null=True, blank=True)
    document_url = models.TextField(verbose_name="URL do documento", null=True, blank=True)

    class Meta:
        verbose_name = "Despesa parlamentar"
        verbose_name_plural = "Despesas parlamentares"
        db_table = "parliamentarian_expenses"
        indexes = [
            models.Index(
                fields=["parliamentarian", "-reference_month"],
                name="idx_expenses_parl_month",
            )
        ]


class ParliamentarianCampaignFinance(models.Model):
    parliamentarian = models.ForeignKey(
        Parliamentarian,
        verbose_name="Parlamentar",
        on_delete=models.CASCADE,
        related_name="campaign_finances",
    )
    election_year = models.SmallIntegerField(verbose_name="Ano da eleição")
    kind = models.TextField(verbose_name="Tipo")
    amount = models.DecimalField(verbose_name="Valor", max_digits=14, decimal_places=2)
    counterparty = models.TextField(verbose_name="Contraparte", null=True, blank=True)
    counterparty_cnpj_cpf = models.TextField(
        verbose_name="CPF ou CNPJ da contraparte", null=True, blank=True
    )
    description = models.TextField(verbose_name="Descrição", null=True, blank=True)

    class Meta:
        verbose_name = "Finança de campanha"
        verbose_name_plural = "Finanças de campanha"
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
        Parliamentarian,
        verbose_name="Parlamentar",
        on_delete=models.CASCADE,
        related_name="investigations",
    )
    case_number = models.TextField(verbose_name="Número do processo", null=True, blank=True)
    court = models.TextField(verbose_name="Tribunal", null=True, blank=True)
    status = models.TextField(verbose_name="Situação")
    subject = models.TextField(verbose_name="Assunto")
    started_at = models.DateField(verbose_name="Iniciado em", null=True, blank=True)
    source_url = models.TextField(verbose_name="URL da fonte", null=True, blank=True)

    class Meta:
        verbose_name = "Investigação parlamentar"
        verbose_name_plural = "Investigações parlamentares"
        db_table = "parliamentarian_investigations"


class ParliamentarianOffice(models.Model):
    parliamentarian = models.OneToOneField(
        Parliamentarian,
        verbose_name="Parlamentar",
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="office",
    )
    reference_date = models.DateField(verbose_name="Data de referência")
    staff_count = models.IntegerField(verbose_name="Número de funcionários", null=True, blank=True)
    gross_salary = models.DecimalField(
        verbose_name="Salário bruto", max_digits=12, decimal_places=2, null=True, blank=True
    )
    has_official_housing = models.BooleanField(
        verbose_name="Possui imóvel funcional", null=True, blank=True
    )
    housing_allowance = models.DecimalField(
        verbose_name="Auxílio-moradia", max_digits=12, decimal_places=2, null=True, blank=True
    )

    class Meta:
        verbose_name = "Gabinete parlamentar"
        verbose_name_plural = "Gabinetes parlamentares"
        db_table = "parliamentarian_office"


class ParliamentarianHousingHistory(models.Model):
    parliamentarian = models.ForeignKey(
        Parliamentarian,
        verbose_name="Parlamentar",
        on_delete=models.CASCADE,
        related_name="housing_history",
    )
    start_date = models.DateField(verbose_name="Data de início")
    end_date = models.DateField(verbose_name="Data de término", null=True, blank=True)
    has_official_housing = models.BooleanField(verbose_name="Possui imóvel funcional")
    housing_allowance = models.DecimalField(
        verbose_name="Auxílio-moradia", max_digits=12, decimal_places=2, null=True, blank=True
    )

    class Meta:
        verbose_name = "Histórico de moradia parlamentar"
        verbose_name_plural = "Históricos de moradia parlamentar"
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
    name = models.TextField(verbose_name="Nome", unique=True)
    kind = models.TextField(verbose_name="Tipo")

    class Meta:
        verbose_name = "Autor institucional"
        verbose_name_plural = "Autores institucionais"
        db_table = "institutional_authors"

    def __str__(self):
        return self.name
