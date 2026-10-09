# Banco de dados

Inventário dos models. As decisões de estrutura, identidade e leitura estão na
[ADR-004](decisions/004-estrutura-do-banco.md). Os models e as migrações são a
referência de campos e restrições.

PostgreSQL 16 com as extensões `pg_trgm`, `unaccent`, `btree_gin`,
`btree_gist` e `vector` (`apps/core/migrations/0001_extensions.py`). Hoje só
`unaccent` é usada. A migração `core/0002_prune_wagtail` remove tabelas
remanescentes do Wagtail/taggit.

## legislatures

| Model | Propósito | Restrições |
| --- | --- | --- |
| `Legislature` | Legislatura (PK `number`) | `end_date > start_date` |
| `Party` | Partido | `acronym` único |
| `Parliamentarian` | Pessoa: nome, gênero, raça, religião, foto etc. | — |
| `ParliamentarianTerm` | Mandato por casa/legislatura | único `(house, external_id, legislature_number)`; FKs `RESTRICT` para legislatura e partido (obrigatório) |
| `ParliamentarianProfileSource` | Perfil normalizado por fonte (câmara, senado, tse…) | único `(source, source_key)` |
| `ParliamentarianPost` | Cargos ocupados | único `(source, source_key)`; datas coerentes |
| `ParliamentarianContact` | Canais de contato | único `(parliamentarian, channel, value)` |
| `ParliamentarianAsset` | Bens declarados | único `(parliamentarian, reference_year)` |
| `ParliamentarianExpense` | Despesas mensais | — |
| `ParliamentarianCampaignFinance` | Gastos e doações de campanha | `kind` em `expense`/`donation` |
| `ParliamentarianInvestigation` | Processos | — |
| `ParliamentarianOffice` | Gabinete (1:1) | — |
| `ParliamentarianHousingHistory` | Histórico de moradia funcional | datas coerentes |
| `InstitutionalAuthor` | Autor não parlamentar (comissão, Executivo…) | `name` único |

## propositions

| Model | Propósito | Restrições |
| --- | --- | --- |
| `Proposition` | Proposição; `is_approved`, `current_content`, promulgação, `raw_payload`, `source_checked_at`, `reconciled_at` | único `(house, external_id)` |
| `PropositionEvent` | Tramitação; `event_at`, `is_countable` | único parcial `(proposition, source_event_id)` quando não nulo; índices por proposição/data |
| `PropositionAuthor` | Autoria com partido/UF do registro | parlamentar **ou** autor institucional (ambos permitidos) |
| `PropositionRapporteur` | Relatoria | FK `RESTRICT` para parlamentar; `committee_id` sem FK |
| `PropositionDocument` | Documento da fonte, papel, revisão, ETag, hash, estado | único `(proposition, source_key)` |
| `PropositionContentVersion` | Texto normalizado e proveniência | único `(proposition, document, text_hash, source_revision)`, nulos iguais |
| `ClassificationRequest` | Pedido de IA | único `(proposition, content_hash, configuration_hash)` |
| `PropositionAnalysis` | Resultado QuitérIA (1:1): categoria, classificação, scores, `content_version` | — |
| `AssessmentOrganization` | Organização avaliadora | `name` único |
| `PropositionAnnotation` | Avaliação humana: categoria, relevância, favorabilidade, comentário | categoria válida (check); FK `PROTECT` para organização; sem unicidade por organização |
| `PropositionEmbedding` | Embedding (1:1) | `BinaryField`; sem índice vetorial nem pipeline |

## taxonomy

| Model | Propósito | Restrições |
| --- | --- | --- |
| `Theme` | Tema hierárquico (`parent`) | `slug` único |
| `AnalyticalTag` | Etiqueta analítica | `slug` único |
| `PropositionTheme` | Tema de uma proposição, com `rank` | único `(proposition, theme)` |
| `PropositionTag` | Etiqueta de uma proposição | único `(proposition, tag)` |
| `PropositionRelation` | Relação entre proposições | único por par/tipo; sem autorrelação; tipo do enum `RelationType` |

## committees

Todos com proveniência (`source`, `source_key`, `url`, `first_seen_at`,
`last_seen_at`) e unicidade parcial por fonte.

| Model | Propósito |
| --- | --- |
| `Committee` | Comissão (único `(house, acronym)`) |
| `CommitteeMembership` | Integrante de comissão |
| `CommitteePresidency` | Presidência de comissão |
| `PropositionCommittee` | Passagem da proposição por comissão (único `(proposition, committee, entered_at)`) |
| `Caucus` | Frente ou bancada (único `(kind, name, legislature)`) |
| `CaucusMembership` | Integrante de frente/bancada |

## activity, norms

| Model | Propósito |
| --- | --- |
| `Vote`, `VoteRecord` | Votação e voto por parlamentar (único `(vote, parliamentarian)`) |
| `PlenarySession`, `AttendanceRecord` | Sessão e presença (único `(session, parliamentarian)`) |
| `Speech` | Discurso |
| `LegalNorm` | Norma (único `(type, number, year)`; índice parcial em `popular_name`) |
| `PropositionAmend` | Alteração de norma por proposição |

As tabelas de `activity` não têm coleta implementada.

## ingestion, subscriptions, newsletters

| Model | Propósito | Restrições |
| --- | --- | --- |
| `RelevanceTerm` | Termo do filtro de relevância | único `(term, mode)` |
| `IngestionRun` | Execução diária ou de reconciliação | — |
| `IngestionCheckpoint` | Cobertura por casa | `house` único |
| `IngestionItem` | Item descoberto numa execução | único `(run, external_id)` |
| `Subscription` | Inscrição: `ast`, `query`, `frequency`, `needs_revalidation`, tokens | tokens únicos |
| `PendingAlert` | Correspondência aguardando o resumo | único `(subscription, proposition)` |
| `AlertDelivery` | Proposição já enviada | único `(subscription, proposition)` |
| `DailyDigestDelivery` | Resumo por endereço/dia | único `(email, delivery_date)` |
| `WeeklyReport` | Relatório congelado e estado da entrega | único `(publication_url, week_start)` |

## Enums (`apps/core/enums.py`)

`House`, `Gender`, `ContactChannel`, `LegalNormType`, `AmendRelationType`,
`VoteChoice`, `AttendanceStatus`, `CommitteeStage`, `CaucusKind`,
`RelationType`, `HumanRelevance` e `PropositionCategory` (10 Categorias
2026; ver [visao-geral.md](visao-geral.md#categorias-2026)).

## Funções SQL

A migração de extensões cria `f_unaccent_lower(text)` e `trg_set_updated_at()`,
sem uso atual: não há triggers, e `updated_at` vem de `auto_now`.

## Geração de diagramas

`mise run db:schema-sql` e `mise run db:dbml` geram `tmp/schema.sql` e
`tmp/schema.dbml` a partir do container `elas-postgres`. São artefatos locais,
não versionados.
