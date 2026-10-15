# Deploy e operação

## Imagem Docker

`Dockerfile` em quatro estágios:

1. **`email_templates`** (Node 22): `npm ci` e `npm run build` dos templates MJML.
2. **`builder`** (uv 0.7):
   - Instala `tini` e Tesseract com dados em português e copia binário, bibliotecas
     e `tessdata` para `/ocr`.
   - Executa `uv python install 3.12` e `uv sync --frozen --no-dev`.
   - Baixa os pesos `azmina/quiteria-2.0` na revisão fixada para
     `/models/quiteria-2.0`.
   - Enxuga a imagem (dados do botocore exceto `sesv2`, testes embutidos).
   - Executa `collectstatic` com settings de prod.
3. **`runtime`** (`gcr.io/distroless/cc-debian12`):
   - Roda como usuário `nonroot` e expõe a porta 8000.
   - `ENTRYPOINT ["tini", "--"]`; o comando padrão é
     `uvicorn config.asgi:application --host 0.0.0.0 --port 8000 --no-access-log`.
   - `HEALTHCHECK` consulta `/health/`.

A imagem não tem shell e **não executa migrações**. O Compose usa
`scripts/start_api.py` (migrate + uvicorn), e o deploy roda `migrate`
explicitamente.

## Kamal

Configuração em `config/deploy.yml`; segredos lidos por nome em `.kamal/secrets`.

- Serviço `elas-no-congresso`, imagem `ghcr.io/institutoazmina/elas-no-congresso-api`,
  usuário SSH `ubuntu`, host em `DEPLOY_HOST`.

| Papel | Comando | Observações | Memória |
| --- | --- | --- | --- |
| `web` | padrão da imagem | Sem kamal-proxy; publicado em `172.17.0.1:8010` e acessado pelo Cloudflare Tunnel | 512 MB |
| `worker` | `celery worker -Q celery`, concorrência 1 | — | 512 MB |
| `ml_worker` | `celery worker -Q ml` | Carrega os dois modelos (~870 MB) | 1536 MB |
| `beat` | `celery beat -S django` | — | 256 MB |

- **Acessório `redis`:** `redis:7-alpine --appendonly yes`, com volume em
  `/var/lib/elas/redis`. O app o acessa em `redis://elas-no-congresso-redis:6379/0`.
- **Banco:** PostgreSQL gerenciado (RDS), configurado por `POSTGRES_*`.
- **Env em claro:**
  - `DJANGO_SETTINGS_MODULE=config.settings.prod`, `PUBLIC_SITE_URL`, `CORS_ALLOWED_ORIGINS`.
  - `REDIS_URL`/`CELERY_BROKER_URL`, `QUITERIA_ENABLED`, `AWS_DEFAULT_REGION`, `AWS_SES_FROM_EMAIL`.
  - Valores repassados das variáveis do repositório: taxa de trace, horário do
    resumo, limite de backfill e as variáveis da newsletter.
- **Segredos:** `SECRET_KEY`, `POSTGRES_HOST/PORT/DB/USER/PASSWORD`,
  `ALLOWED_HOSTS`, `SITE_BASE_URL`. `SUBSTACK_COOKIES_STRING` só entra quando a
  newsletter está ligada ou o cookie está definido; `SITE_DEPLOY_GITHUB_TOKEN` e
  `CMS_CLOUDFRONT_DISTRIBUTION_ID`, quando definidos.
- **E-mail:** o app não recebe chaves AWS; o SES usa a IAM role da instância.

## Workflow de deploy

`.github/workflows/deploy.yml`:

- **Gatilhos:** push em `main` e execução manual.
- **Concorrência:** grupo `deploy-<ref>`, compartilhado com os workflows operacionais.

Etapas:

1. Checkout, Ruby 3.3, `gem install kamal -v 2.12.0`, Buildx, ssh-agent e
   `ssh-keyscan` do host.
2. `kamal app stop --roles web` para liberar a porta 8010.
3. `kamal setup`: sobe acessórios, faz build, push e deploy.
4. `kamal app exec --reuse --roles web "python manage.py migrate --noinput"`.
5. `kamal app exec --reuse --roles web "python manage.py ingestion_sync --mode bootstrap"`.
6. `kamal app exec --reuse --roles web "python manage.py cms_publish_defaults"`:
   publica as imagens originais do CMS que ainda não estão no bucket.

| Tipo | Itens |
| --- | --- |
| Segredos do GitHub | `DEPLOY_HOST`, `SSH_PRIVATE_KEY`, `SECRET_KEY`, `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `ALLOWED_HOSTS`, `SITE_BASE_URL`, `SUBSTACK_COOKIES_STRING`, `SITE_DEPLOY_GITHUB_TOKEN`, `CMS_CLOUDFRONT_DISTRIBUTION_ID`; `GITHUB_TOKEN` autentica no GHCR |
| Variáveis do repositório | `ACTIVITY_EXPLORER_TRACE_SAMPLE_RATE`, `WEEKLY_NEWSLETTER_ENABLED`, `WEEKLY_NEWSLETTER_BATCH_SIZE`, `CLASSIFICATION_BACKFILL_DAILY_LIMIT`, `SUBSTACK_PUBLICATION_URL` |

## Workflows operacionais

Todos são manuais e rodam comandos no container `web` existente.

| Workflow | Guia |
| --- | --- |
| `ingestion-sync.yml` | [ingestao.md](ingestao.md#comando-ingestion_sync) |
| `classification-backfill.yml` | [ingestao.md](ingestao.md#comando-classification_backfill) |
| `newsletter-draft.yml` | [newsletter.md](newsletter.md#workflow-newsletter-draftyml) |
| `enrich-parliamentarian-religions.yml` | [ingestao.md](ingestao.md#outros-comandos) |

Comandos avulsos em produção:

```bash
kamal app exec --reuse --roles web "python manage.py ingestion_sync --mode status"
```

## Agenda do Celery Beat

O Beat usa `DatabaseScheduler`. As entradas abaixo são definidas em
`config/settings/base.py` e sincronizadas com o banco quando o Beat inicia.
Horários em `America/Sao_Paulo`.

| Horário | Entrada | Tarefa | Fila |
| --- | --- | --- | --- |
| 03:00 | `enrich-parliamentarian-profiles-daily` | `enrich_parliamentarian_profiles` | celery |
| 04:00 | `cleanup-unconfirmed-subscriptions` | `cleanup_unconfirmed_subscriptions` | celery |
| 06:00 | `ingest-camara-daily` | `ingest_camara` | celery |
| 06:10 | `ingest-senado-daily` | `ingest_senado` | celery |
| 06:30 | `refresh-enacted-proposition-statuses-daily` | `reconcile_daily_propositions` | celery |
| 06:45 | `backfill-missing-evaluations-daily` | `backfill_missing_evaluations` | celery |
| a cada 15 min | `recover-content-work` | `recover_pending_content` | celery |
| `DAILY_DIGEST_TIME` (09:00) | `daily-digest` | `send_daily_digest` | celery |
| seg 04:00 / 06:35 / 06:45 / 07:00 | tarefas semanais | só com `WEEKLY_NEWSLETTER_ENABLED` | celery |

A entrada das 06:30 tem nome legado, mas executa a reconciliação. Tarefas de
documento e classificação são enfileiradas em `ml` por essas rotinas.

## Saúde e monitoramento

- `GET /health/`: liveness, usado pelo `HEALTHCHECK` da imagem.
- `GET /health/ready/`: banco e cache; 503 se algum falhar.
- `python manage.py ingestion_sync --mode status`: cobertura por casa e
  últimas execuções.
- `python manage.py classification_backfill --mode status`: cobertura de
  avaliações.
- Admin: execuções/itens de ingestão, relatórios semanais e inscrições.
- Logs estruturados do explorer com `ACTIVITY_EXPLORER_TRACE_SAMPLE_RATE > 0`.

## Checklist de operação

| Sintoma | Verificação | Ação |
| --- | --- | --- |
| Painel sem novidades | `ingestion_sync --mode status`; itens `failed` no admin | `--mode retry`; corrigir item que sempre falha |
| Lacuna longa no Senado | `covered_until` com mais de 30 dias | `--mode catchup` |
| Proposições sem avaliação | `classification_backfill --mode status`; worker `ml` ativo | `--mode queue` ou `retry` |
| Resumo diário não saiu | Pendências no admin; logs `AnymailError`; SES fora do sandbox | Corrigir SES; pendências são preservadas |
| Radar `auth_required` | `weekly_newsletter --check-auth` | Renovar `SUBSTACK_COOKIES_STRING` e redeployar |
| Radar `uncertain` | Procurar o título no Substack | `--report-id N --attach-draft-id ID --deliver` |
| Radar bloqueado por cobertura | `collection` do relatório no admin | Regularizar a ingestão ou usar `--allow-incomplete` |
| Painel defasado após edição | Alteração fora dos sinais de invalidação | Aguardar 5 min ou salvar a proposição |
