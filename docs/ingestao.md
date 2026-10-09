# Ingestão, documentos e QuitérIA

Guia operacional. As decisões e garantias estão na
[ADR-002](decisions/002-daily-ingestion-content-versions.md).

## Visão do pipeline

1. `ingest_camara` (06:00) e `ingest_senado` (06:10) abrem um `IngestionRun`
   diário por casa e descobrem mudanças desde o checkpoint, com dois dias de
   sobreposição. Sem checkpoint, a janela começa 14 dias atrás (16 com a
   sobreposição).
2. Cada mudança vira um `IngestionItem` (`pending`). Lotes de
   `INGESTION_BATCH_SIZE` itens são processados por `sync_daily_batch`, um após
   o outro, com 5 s de intervalo.
3. Proposições novas passam pelo filtro de relevância (`theme_assert`); as
   conhecidas são atualizadas diretamente.
4. Documentos são registrados e verificados na fila `ml`
   (`check_proposition_document`); textos novos geram `ClassificationRequest`
   (`run_classification_request`).
5. Se a descoberta terminou e nenhum item falhou, o checkpoint avança e a casa
   passa a ter cobertura até o fim da janela.
6. `reconcile_daily_propositions` (06:30) revisita até 600 proposições por casa
   sem verificação ou verificadas há mais de 7 dias.
7. `backfill_missing_evaluations` (06:45) enfileira até 600 proposições sem
   avaliação.
8. `recover_pending_content` (a cada 15 min) retoma execuções em andamento e
   até 100 documentos e 100 pedidos pendentes, falhos ou abandonados há 90 min,
   com no máximo 3 tentativas.

### Fontes

| Fonte | Cliente | Uso |
| --- | --- | --- |
| Câmara (Dados Abertos) | `apps/ingestion/clients/camara.py` | Proposições por janela de tramitação, detalhe, autorias, tramitações, deputados, frentes e órgãos |
| Senado (Dados Abertos) | `apps/ingestion/clients/senado.py` | `/processo?numdias=N&v=1` (máx. 30 dias, inclui encerrados), processo, documentos, senadores, comissões, filiações, lideranças, cargos e páginas de frentes |
| TSE | `apps/ingestion/clients/tse.py` | Arquivos de candidaturas 2018/2022 |

O cliente base (`clients/base.py`) aplica `INGESTION_REQUESTS_PER_SECOND` por
host (compartilhado via Redis) e até 3 tentativas para erros de transporte,
429 e 5xx, respeitando `Retry-After` até 60 s.

No Senado, `codigoMateria` é a identidade; sem ele, usa-se o negativo do ID do
processo.

### Filtro de relevância

- Termos em `RelevanceTerm` (editáveis no admin), com o vocabulário de
  `relevance_defaults.py` como fallback; cache de 300 s, invalidado ao salvar
  ou apagar um termo.
- Palavras e expressões completas, sem diferenciar caixa e preservando acentos.
  Regras combinadas (`termo + outro`) exigem todos os componentes; uma regra
  combinada sem ` + ` vira `termo + MULHER`.
- Ordem: ementa (e ementa detalhada, na Câmara; ementa do processo e da
  listagem, no Senado); sem correspondência, o inteiro teor é baixado e, se
  necessário, passa por OCR de forma síncrona.
- Sem link ou com CAPTCHA reconhecido, decide-se só pelas ementas. Erro de rede,
  PDF inválido ou texto vazio fazem o item falhar e ser retomado.

### Documentos e OCR

- Documentos de até 20 MB, timeout de 60 s, com ETag/Last-Modified.
- `pypdf` primeiro; páginas com menos de 500 caracteres vão para PyMuPDF +
  Tesseract `por` a 200 DPI, e o OCR só é mantido se acrescentar mais de 200
  caracteres. Sem Tesseract, fica só o `pypdf`.
- Substitutivos e redações integrais identificáveis podem substituir o conteúdo
  analisado; um original nunca substitui um substitutivo, e datas de fonte mais
  antigas são ignoradas.

### QuitérIA 2.0

- Dois classificadores BERT locais (`azmina/quiteria-2.0`, revisão fixada),
  carregados com `local_files_only=True` no worker `ml`.
- Entrada: partido, gênero e UF da primeira autoria + texto selecionado (ementa
  como fallback), truncada em 512 tokens.
- Tema: uma das 10 categorias. Favorabilidade: probabilidade desfavorável
  ≥ `QUITERIA_FAVORABILITY_THRESHOLD` → `1` (desfavorável); abaixo → `0`.
- Pedido único por proposição + hash do texto + hash da configuração (modelo,
  revisão, limiar e versão de entrada). Mudar limiar ou revisão torna pedidos
  pendentes `superseded`.
- Resultados de classificação normal disparam correspondência de alertas;
  pedidos de backfill (`only_if_unevaluated`) não.

## Comando `ingestion_sync`

```bash
python manage.py ingestion_sync --mode status     # padrão
```

| Modo | Efeito |
| --- | --- |
| `status` | Mostra checkpoints e as 6 últimas execuções; não altera nada |
| `daily` | Enfileira `ingest_camara` e `ingest_senado` |
| `bootstrap` | `daily` + reconciliação com `full_baseline=True` (teto de 100000 por casa enquanto a baseline não terminar) |
| `retry` | Enfileira as ingestões, reinicia itens falhos de execuções `failed`/`running`, redespacha os lotes e chama `recover_pending_content` |
| `catchup` | Zera **todos** os checkpoints, apaga `reconciled_at` de **todas** as proposições e enfileira ingestão + reconciliação completa |

Todos os modos, exceto `status`, desativam a tarefa periódica legada
`refresh_enacted_proposition_statuses`.

O deploy executa `--mode bootstrap` após as migrações.

### Quando usar cada modo

- **Coleta atrasada por falha pontual**: `retry`.
- **Lacuna de vários dias**: `retry` primeiro. Se a janela travada do Senado
  ultrapassar 30 dias, use `catchup`; ele reinicia a cobertura recente e audita o
  inventário conhecido, mas não recupera proposições desconhecidas fora da
  janela nem afirma continuidade sobre a lacuna.
- **Banco novo**: `bootstrap`.

### Item que sempre falha

Uma execução `failed` é reaproveitada no próximo disparo, sem nova descoberta:
o checkpoint só avança quando todos os itens concluem. Se um item falha de forma
permanente, a cobertura daquela casa para e mudanças mais novas não são
descobertas. Inspecione no admin (**Ingestão → Itens**, filtro `failed`) o
`error` do item, corrija a causa (fonte, documento) e use `--mode retry`. Se a
janela do Senado passar de 30 dias, use `--mode catchup`.

## Comando `classification_backfill`

```bash
python manage.py classification_backfill --mode preview
python manage.py classification_backfill --mode queue --limit 100
```

| Modo | Efeito |
| --- | --- |
| `preview` / `status` | Mostram a cobertura de avaliações (equivalentes) |
| `queue` | Enfileira pedidos `only_if_unevaluated` para proposições sem avaliação, usando texto já armazenado |
| `retry` | Reenfileira pedidos de backfill falhos ou abandonados |

`--limit 0` (padrão) significa sem limite. São excluídas proposições com
anotação humana, revisão legada ou avaliação válida (categoria + classificação
0/1). Enfileirar não significa classificar: acompanhe com `status`.

## Outros comandos

| Comando | Uso |
| --- | --- |
| `refresh_enacted_propositions [--house camara\|senado] [--limit N] [--strict]` | Atualiza status, promulgação e eventos de proposições com anotação humana de favorabilidade |
| `backfill_proposition_events [--house] [--offset N] [--limit N]` | Reconstrói o histórico de eventos (tramitações da Câmara; processo ou `/materia/movimentacoes` no Senado) |
| `import_parliamentarian_religions [--url URL \| --csv-path P] [--dry-run]` | Importa religião de deputados da planilha pública (exportada como CSV pela URL padrão) |

## Enriquecimento de parlamentares (03:00)

`enrich_parliamentarian_profiles`, também disparável no admin
(**Parlamentares → Atualizar perfis**), com trava de 1 h:

1. Lê as composições atuais (`/deputados`, `/senador/lista/atual`; esperadas 513
   e 81) e atualiza mandatos por legislatura.
2. Encerra, com a data de ontem, mandatos de quem saiu, **somente** se a
   composição veio íntegra (tamanho certo, sem duplicatas, legislatura
   coerente, sem falhas).
3. Identifica a pessoa só por evidência oficial já persistida: mandatos e
   perfis por fonte com o mesmo ID externo. O nome sozinho nunca reaproveita um
   cadastro; sem evidência, cria-se uma pessoa nova. Conflitos geram
   `ReconciliationError`.
4. Normaliza perfis por fonte (`ParliamentarianProfileSource`), incluindo
   profissões e formação acadêmica do Senado.
5. TSE: cruza cargo + UF + nome completo normalizado (Câmara: 2022; Senado:
   2018 e 2022; partido desempata) e grava nascimento, raça, escolaridade e
   ocupação. Limites de download: 128 MB por arquivo e proteções contra zip bomb.
6. Frentes do Senado: raspagem de catálogo, conselho e composição em hosts HTTPS
   permitidos (2 MB por página, até 200 páginas, 100 frentes, 3 redirects).
7. Vínculos institucionais: frentes e órgãos da Câmara; comissões, filiações,
   lideranças e cargos do Senado, por chave do provedor, sem casar por nome.

## Estados persistidos

| Model | Estados |
| --- | --- |
| `IngestionRun` | `running`, `success`, `failed`; `kind` `daily` ou `reconcile` |
| `IngestionItem` | `pending`, `succeeded`, `skipped`, `failed` (até 3 tentativas por execução) |
| `IngestionCheckpoint` | Sem status: `covered_since`, `covered_until`, `baseline_complete`, `active_run` |
| `PropositionDocument` | `pending`, `fetching`, `ready`, `failed` |
| `ClassificationRequest` | `pending`, `running`, `succeeded`, `failed`, `superseded` |

Descoberta, lote e reconciliação usam travas de cache de 1800 s.

## Workflows do GitHub

Todos são manuais (`workflow_dispatch`) e executam o comando dentro do container
`web` em produção com `kamal app exec --reuse --roles web`.

| Workflow | Entradas | Comando |
| --- | --- | --- |
| `ingestion-sync.yml` | `mode` (padrão `status`) | `ingestion_sync --mode` |
| `classification-backfill.yml` | `mode`, `limit` (padrão `0`) | `classification_backfill`; saída no resumo do job |
| `enrich-parliamentarian-religions.yml` | `dry_run` (padrão `true`) | `import_parliamentarian_religions` |

`ingestion-sync` e `classification-backfill` só rodam em `main` e compartilham o
grupo de concorrência `deploy-<ref>` com o deploy.
