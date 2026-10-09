from django.db import models

from apps.core.enums import House, HumanRelevance, PropositionCategory
from apps.legislatures.models import InstitutionalAuthor, Parliamentarian, Party


class Proposition(models.Model):
    house = models.CharField(verbose_name="Casa legislativa", max_length=10, choices=House.choices)
    external_id = models.BigIntegerField(verbose_name="Identificador externo")
    type_code = models.TextField(verbose_name="Tipo de proposição")
    number_label = models.TextField(verbose_name="Identificação da proposição")
    number = models.IntegerField(verbose_name="Número")
    year = models.SmallIntegerField(verbose_name="Ano")
    presented_at = models.DateField(verbose_name="Apresentada em")
    ementa = models.TextField(verbose_name="Ementa")
    keywords = models.TextField(verbose_name="Palavras-chave", null=True, blank=True)
    full_text_url = models.TextField(verbose_name="URL do inteiro teor", null=True, blank=True)
    full_text = models.TextField(verbose_name="Inteiro teor", null=True, blank=True)
    source_checked_at = models.DateTimeField(
        verbose_name="Fonte verificada em", null=True, blank=True, db_index=True
    )
    reconciled_at = models.DateTimeField(
        verbose_name="Reconciliado em", null=True, blank=True, db_index=True
    )
    current_content = models.ForeignKey(
        "PropositionContentVersion",
        verbose_name="Conteúdo atual",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="selected_by",
    )
    tramitation_url = models.TextField(verbose_name="URL da tramitação", null=True, blank=True)
    current_status = models.TextField(verbose_name="Situação atual", null=True, blank=True)
    current_status_code = models.IntegerField(
        verbose_name="Código da situação atual", null=True, blank=True
    )
    regime = models.TextField(verbose_name="Regime", null=True, blank=True)
    scope = models.TextField(verbose_name="Âmbito", null=True, blank=True)
    appreciation_mode = models.TextField(verbose_name="Forma de apreciação", null=True, blank=True)
    is_active = models.BooleanField(verbose_name="Ativa", default=True)
    # A coleta é intencionalmente abrangente. A publicação, porém, exige
    # curadoria: uma proposição nova não pode aparecer no painel público até
    # que alguém da equipe a aprove no gerenciador.
    is_approved = models.BooleanField(
        verbose_name="Aprovada para publicação", default=False, db_index=True
    )
    enacted_law_type = models.TextField(
        verbose_name="Tipo da norma resultante", null=True, blank=True
    )
    enacted_law_number = models.IntegerField(
        verbose_name="Número da norma resultante", null=True, blank=True
    )
    enacted_law_year = models.SmallIntegerField(
        verbose_name="Ano da norma resultante", null=True, blank=True
    )
    enacted_at = models.DateField(verbose_name="Convertida em norma em", null=True, blank=True)
    originating_house = models.CharField(
        verbose_name="Casa de origem", max_length=10, choices=House.choices, null=True, blank=True
    )
    raw_payload = models.JSONField(verbose_name="Dados originais", null=True, blank=True)
    created_at = models.DateTimeField(verbose_name="Criado em", auto_now_add=True)
    updated_at = models.DateTimeField(verbose_name="Atualizado em", auto_now=True)

    class Meta:
        verbose_name = "Proposição"
        verbose_name_plural = "Proposições"
        db_table = "propositions"
        constraints = [
            models.UniqueConstraint(
                fields=["house", "external_id"], name="propositions_house_external_id"
            )
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
        Proposition, verbose_name="Proposição", on_delete=models.CASCADE, related_name="events"
    )
    # Identificador estável da API de origem. Evita duplicar o histórico em
    # reprocessamentos diários e no backfill inicial.
    source_event_id = models.CharField(
        verbose_name="Identificador do evento na fonte", max_length=128, null=True, blank=True
    )
    source_kind = models.CharField(verbose_name="Tipo de fonte", max_length=32, default="status")
    event_at = models.DateTimeField(verbose_name="Data do evento")
    sequence = models.IntegerField(verbose_name="Sequência", null=True, blank=True)
    title = models.TextField(verbose_name="Título", null=True, blank=True)
    description = models.TextField(verbose_name="Descrição", null=True, blank=True)
    situation = models.TextField(verbose_name="Situação", null=True, blank=True)
    dispatch = models.TextField(verbose_name="Despacho", null=True, blank=True)
    committee_id = models.BigIntegerField(
        verbose_name="Identificador da comissão", null=True, blank=True
    )
    committee_acronym = models.CharField(
        verbose_name="Sigla da comissão", max_length=32, null=True, blank=True
    )
    committee_name = models.TextField(verbose_name="Nome da comissão", null=True, blank=True)
    is_countable = models.BooleanField(verbose_name="Contabilizável", default=True)
    raw_payload = models.JSONField(verbose_name="Dados originais", null=True, blank=True)

    class Meta:
        verbose_name = "Evento de tramitação"
        verbose_name_plural = "Eventos de tramitação"
        db_table = "proposition_events"
        indexes = [
            models.Index(fields=["proposition", "-event_at"], name="idx_events_prop_date"),
            models.Index(fields=["-event_at"], name="idx_events_date"),
            models.Index(fields=["proposition", "source_event_id"], name="idx_events_prop_source"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["proposition", "source_event_id"],
                condition=models.Q(source_event_id__isnull=False),
                name="proposition_events_source_id",
            )
        ]


class PropositionAuthor(models.Model):
    proposition = models.ForeignKey(
        Proposition, verbose_name="Proposição", on_delete=models.CASCADE, related_name="authors"
    )
    parliamentarian = models.ForeignKey(
        Parliamentarian,
        verbose_name="Parlamentar",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="authored_propositions",
    )
    institutional_author = models.ForeignKey(
        InstitutionalAuthor,
        verbose_name="Autor institucional",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="authored_propositions",
    )
    party = models.ForeignKey(
        Party,
        verbose_name="Partido",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="authored_propositions",
    )
    state_at_authorship = models.CharField(
        verbose_name="UF na autoria", max_length=2, null=True, blank=True
    )
    order_index = models.SmallIntegerField(verbose_name="Ordem", default=1)

    class Meta:
        verbose_name = "Autoria de proposição"
        verbose_name_plural = "Autorias de proposições"
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
        Proposition, verbose_name="Proposição", on_delete=models.CASCADE, related_name="rapporteurs"
    )
    parliamentarian = models.ForeignKey(
        Parliamentarian,
        verbose_name="Parlamentar",
        on_delete=models.RESTRICT,
        related_name="rapporteurships",
    )
    committee_id = models.BigIntegerField(
        verbose_name="Identificador da comissão", null=True, blank=True
    )
    party = models.ForeignKey(
        Party,
        verbose_name="Partido",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="rapporteurships",
    )
    designated_at = models.DateField(verbose_name="Designado em")
    ended_at = models.DateField(verbose_name="Encerrado em", null=True, blank=True)

    class Meta:
        verbose_name = "Relatoria de proposição"
        verbose_name_plural = "Relatorias de proposições"
        db_table = "proposition_rapporteurs"
        indexes = [
            models.Index(fields=["proposition"], name="idx_rapp_prop"),
            models.Index(fields=["parliamentarian"], name="idx_rapp_parl_current"),
        ]

    @property
    def is_current(self):
        return self.ended_at is None


class PropositionAnalysis(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        SUCCEEDED = "succeeded", "Concluída"
        FAILED = "failed", "Falhou"

    proposition = models.OneToOneField(
        Proposition,
        verbose_name="Proposição",
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="analysis",
    )
    # Resultado do modelo ``tema``. A categoria usa exatamente a taxonomia
    # editorial do produto; os scores brutos ficam guardados para auditoria.
    theme_category = models.CharField(
        verbose_name="Categoria temática",
        max_length=32,
        choices=PropositionCategory.choices,
        null=True,
        blank=True,
    )
    theme_confidence = models.DecimalField(
        verbose_name="Confiança da categoria temática",
        max_digits=5,
        decimal_places=4,
        null=True,
        blank=True,
    )
    theme_scores = models.JSONField(verbose_name="Pontuações temáticas", default=dict, blank=True)
    # Resultado do modelo ``favorabilidade``. ``classification`` mantém o
    # índice decidido pelo cutoff e ``classification_probability`` é P(classe 1
    # = desfavorável), preservando os campos já existentes.
    classification = models.SmallIntegerField(verbose_name="Classificação", null=True, blank=True)
    classification_probability = models.DecimalField(
        verbose_name="Probabilidade da classificação",
        max_digits=5,
        decimal_places=4,
        null=True,
        blank=True,
    )
    favorability_scores = models.JSONField(
        verbose_name="Pontuações de favorabilidade", default=dict, blank=True
    )
    llm_position = models.SmallIntegerField(
        verbose_name="Posicionamento do modelo de linguagem", null=True, blank=True
    )
    final_position_score = models.DecimalField(
        verbose_name="Pontuação final de posicionamento",
        max_digits=5,
        decimal_places=4,
        null=True,
        blank=True,
    )
    expert_opinion = models.TextField(verbose_name="Parecer de especialista", null=True, blank=True)
    expert_id = models.BigIntegerField(
        verbose_name="Identificador de especialista", null=True, blank=True
    )
    ai_summary = models.TextField(verbose_name="Resumo por IA", null=True, blank=True)
    quiterometer_score = models.FloatField(
        verbose_name="Pontuação do Quiterômetro", null=True, blank=True
    )
    model_id = models.CharField(
        verbose_name="Identificador do modelo", max_length=128, null=True, blank=True
    )
    model_revision = models.CharField(
        verbose_name="Revisão do modelo", max_length=64, null=True, blank=True
    )
    input_hash = models.CharField(
        verbose_name="Hash da entrada", max_length=64, null=True, blank=True
    )
    analysis_status = models.CharField(
        verbose_name="Situação da análise",
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
    )
    analysis_error = models.TextField(verbose_name="Erro da análise", null=True, blank=True)
    analyzed_at = models.DateTimeField(verbose_name="Analisado em", auto_now_add=True)
    completed_at = models.DateTimeField(verbose_name="Concluído em", null=True, blank=True)
    content_version = models.ForeignKey(
        "PropositionContentVersion",
        verbose_name="Versão do conteúdo",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="analyses",
    )

    class Meta:
        verbose_name = "Análise de proposição"
        verbose_name_plural = "Análises de proposições"
        db_table = "proposition_analysis"
        indexes = [
            models.Index(fields=["quiterometer_score"], name="idx_analysis_quitero"),
            models.Index(fields=["analysis_status"], name="idx_analysis_status"),
        ]


class PropositionDocument(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        FETCHING = "fetching", "Extraindo"
        READY = "ready", "Verificado"
        FAILED = "failed", "Falhou"

    proposition = models.ForeignKey(
        Proposition, verbose_name="Proposição", on_delete=models.CASCADE, related_name="documents"
    )
    source_key = models.CharField(verbose_name="Identificador na fonte", max_length=128)
    role = models.CharField(
        verbose_name="Tipo de documento",
        max_length=16,
        choices=[("original", "Original"), ("replacement", "Texto substitutivo")],
    )
    url = models.TextField(verbose_name="URL")
    source_revision = models.CharField(verbose_name="Revisão da fonte", max_length=64)
    checked_revision = models.CharField(
        verbose_name="Revisão verificada", max_length=64, blank=True
    )
    analyze_on_first = models.BooleanField(
        verbose_name="Analisar na primeira extração", default=True
    )
    source_date = models.DateTimeField(verbose_name="Data da fonte", null=True, blank=True)
    etag = models.TextField(verbose_name="Identificador de versão (ETag)", blank=True)
    last_modified = models.TextField(verbose_name="Última modificação na fonte", blank=True)
    bytes_hash = models.CharField(verbose_name="Hash do arquivo", max_length=64, blank=True)
    status = models.CharField(
        verbose_name="Situação",
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    attempts = models.PositiveIntegerField(verbose_name="Tentativas", default=0)
    attempted_at = models.DateTimeField(verbose_name="Última tentativa em", null=True, blank=True)
    checked_at = models.DateTimeField(verbose_name="Verificado em", null=True, blank=True)
    error = models.CharField(verbose_name="Erro", max_length=200, blank=True)

    class Meta:
        verbose_name = "Documento de proposição"
        verbose_name_plural = "Documentos de proposições"
        constraints = [
            models.UniqueConstraint(
                fields=["proposition", "source_key"], name="proposition_document_source"
            )
        ]


class PropositionContentVersion(models.Model):
    proposition = models.ForeignKey(
        Proposition,
        verbose_name="Proposição",
        on_delete=models.CASCADE,
        related_name="content_versions",
    )
    document = models.ForeignKey(
        PropositionDocument,
        verbose_name="Documento",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="versions",
    )
    text = models.TextField(verbose_name="Texto")
    text_hash = models.CharField(verbose_name="Hash do texto", max_length=64)
    source_url = models.TextField(verbose_name="URL da fonte", blank=True)
    source_revision = models.CharField(verbose_name="Revisão da fonte", max_length=64, blank=True)
    source_date = models.DateTimeField(verbose_name="Data da fonte", null=True, blank=True)
    extraction_version = models.CharField(
        verbose_name="Versão da extração", max_length=32, default="pdf-ocr-v1"
    )
    created_at = models.DateTimeField(verbose_name="Criado em", auto_now_add=True)

    class Meta:
        verbose_name = "Versão do conteúdo da proposição"
        verbose_name_plural = "Versões do conteúdo das proposições"
        constraints = [
            models.UniqueConstraint(
                fields=["proposition", "document", "text_hash", "source_revision"],
                name="proposition_content_document_hash",
                nulls_distinct=False,
            )
        ]


class ClassificationRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        RUNNING = "running", "Em execução"
        SUCCEEDED = "succeeded", "Concluída"
        FAILED = "failed", "Falhou"
        SUPERSEDED = "superseded", "Substituída"

    proposition = models.ForeignKey(
        Proposition,
        verbose_name="Proposição",
        on_delete=models.CASCADE,
        related_name="classification_requests",
    )
    content_version = models.ForeignKey(
        PropositionContentVersion,
        verbose_name="Versão do conteúdo",
        on_delete=models.CASCADE,
        related_name="classification_requests",
    )
    content_hash = models.CharField(verbose_name="Hash do conteúdo", max_length=64)
    configuration_hash = models.CharField(verbose_name="Hash da configuração", max_length=64)
    input_text = models.TextField(verbose_name="Texto de entrada")
    input_hash = models.CharField(verbose_name="Hash da entrada", max_length=64)
    model_id = models.CharField(verbose_name="Identificador do modelo", max_length=128)
    model_revision = models.CharField(verbose_name="Revisão do modelo", max_length=64)
    threshold = models.FloatField(verbose_name="Limiar")
    only_if_unevaluated = models.BooleanField(verbose_name="Somente se não avaliada", default=False)
    status = models.CharField(
        verbose_name="Situação",
        max_length=16,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
    )
    attempts = models.PositiveIntegerField(verbose_name="Tentativas", default=0)
    attempted_at = models.DateTimeField(verbose_name="Última tentativa em", null=True, blank=True)
    completed_at = models.DateTimeField(verbose_name="Concluído em", null=True, blank=True)
    result = models.JSONField(verbose_name="Resultado", default=dict)
    error = models.CharField(verbose_name="Erro", max_length=200, blank=True)

    class Meta:
        verbose_name = "Solicitação de classificação"
        verbose_name_plural = "Solicitações de classificação"
        constraints = [
            models.UniqueConstraint(
                fields=["proposition", "content_hash", "configuration_hash"],
                name="classification_content_configuration",
            )
        ]


class AssessmentOrganization(models.Model):
    """Organização da sociedade civil que avalia proposições (avaliadora)."""

    name = models.TextField(verbose_name="Nome", unique=True)
    created_at = models.DateTimeField(verbose_name="Criado em", auto_now_add=True)

    class Meta:
        verbose_name = "Organização avaliadora"
        verbose_name_plural = "Organizações avaliadoras"
        db_table = "assessment_organizations"

    def __str__(self):
        return self.name


class PropositionAnnotation(models.Model):
    """Anotação humana de uma avaliadora sobre uma proposição."""

    proposition = models.ForeignKey(
        Proposition, verbose_name="Proposição", on_delete=models.CASCADE, related_name="annotations"
    )
    organization = models.ForeignKey(
        AssessmentOrganization,
        verbose_name="Organização avaliadora",
        on_delete=models.PROTECT,
        related_name="annotations",
    )
    # Avaliação: Favorável -> True, Desfavorável -> False, vazio -> NULL
    is_favorable = models.BooleanField(verbose_name="Favorável", null=True, blank=True)
    # Há ressalvas?: S -> True, N/vazio -> False
    has_caveats = models.BooleanField(verbose_name="Há ressalvas", default=False)
    relevance = models.CharField(
        verbose_name="Relevância",
        max_length=20,
        choices=HumanRelevance.choices,
        default=HumanRelevance.RELEVANTE,
    )
    # nota av (1 / -1) e nota rel (2 / 1)
    assessment_score = models.SmallIntegerField(
        verbose_name="Nota da avaliação", null=True, blank=True
    )
    relevance_score = models.SmallIntegerField(
        verbose_name="Nota de relevância", null=True, blank=True
    )
    # Categorias 2026: taxonomia fechada, obrigatória. Substitui o antigo
    # `human_theme` como campo de trabalho das avaliadoras.
    category = models.CharField(
        verbose_name="Categoria", max_length=32, choices=PropositionCategory.choices
    )
    # Antigo `human_theme` ("Tema (class humana)"): texto livre da planilha, com
    # granularidade que as 10 categorias colapsam (Feminicídio, Lei Maria da
    # Penha, Microcefalia...). Preservado como histórico, fora dos formulários.
    legacy_theme = models.TextField(verbose_name="Tema histórico", null=True, blank=True)
    comments = models.TextField(verbose_name="Comentários", null=True, blank=True)
    created_at = models.DateTimeField(verbose_name="Criado em", auto_now_add=True)
    updated_at = models.DateTimeField(verbose_name="Atualizado em", auto_now=True)

    class Meta:
        verbose_name = "Anotação de proposição"
        verbose_name_plural = "Anotações de proposições"
        db_table = "proposition_annotations"
        constraints = [
            # `choices` só vale em forms/full_clean; o check garante no banco
            # que scripts e shell também fiquem dentro da taxonomia.
            models.CheckConstraint(
                condition=models.Q(category__in=PropositionCategory.values),
                name="proposition_annotations_category_check",
            ),
        ]

    def save(self, *args, **kwargs):
        # Invariante: relevance nunca é nulo — cai em 'relevante' se vier None.
        if self.relevance is None:
            self.relevance = HumanRelevance.RELEVANTE
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.organization} · {self.proposition}"


class PropositionEmbedding(models.Model):
    proposition = models.OneToOneField(
        Proposition,
        verbose_name="Proposição",
        on_delete=models.CASCADE,
        primary_key=True,
        related_name="embedding",
    )
    model_name = models.TextField(verbose_name="Nome do modelo")
    # Reservado: nenhuma migração converte a coluna para `vector` nem cria índice
    # vetorial, e não há pipeline gerando embeddings.
    embedding = models.BinaryField(verbose_name="Representação vetorial")
    generated_at = models.DateTimeField(verbose_name="Gerado em", auto_now_add=True)

    class Meta:
        verbose_name = "Representação vetorial de proposição"
        verbose_name_plural = "Representações vetoriais de proposições"
        db_table = "proposition_embeddings"
