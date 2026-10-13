# Configuração

As configurações ficam em `config/settings/` e leem variáveis com
`python-decouple` (ambiente ou `.env`). O módulo padrão é `config.settings.dev`
(`manage.py`, `asgi.py`, `wsgi.py`, `celery.py`); o Kamal usa
`config.settings.prod` e o pytest usa `config.settings.test`.

## Variáveis de ambiente

### Django e infraestrutura

| Variável | Padrão | Uso |
| --- | --- | --- |
| `DJANGO_SETTINGS_MODULE` | `config.settings.dev` | Módulo de configurações |
| `SECRET_KEY` | `django-insecure-changeme-in-prod` | Chave do Django; obrigatória em produção |
| `DEBUG` | `True` | Sobrescrita por cada módulo: dev `True`, prod e test `False` |
| `ALLOWED_HOSTS` | `*` (lista separada por vírgula) | dev força `["*"]` |
| `ADMIN_URL` | `admin/` | Caminho do admin, com barra final |
| `POSTGRES_DB` / `POSTGRES_USER` / `POSTGRES_PASSWORD` | `elas` / `elas` / `elas` | Banco (`CONN_MAX_AGE=60`, `connect_timeout=10`) |
| `POSTGRES_HOST` / `POSTGRES_PORT` | `localhost` / `5432` | Endereço do banco |
| `REDIS_URL` | `redis://localhost:6379/0` | Cache e sessões |
| `CELERY_BROKER_URL` | valor de `REDIS_URL` | Broker do Celery |
| `TEST_DATABASE_URL` | — | Apenas `test`; substitui o banco `legislativo_test` |

Não há `DATABASE_URL`: o banco é configurado só por `POSTGRES_*`.

### URLs públicas e CORS

| Variável | Padrão | Uso |
| --- | --- | --- |
| `SITE_BASE_URL` | `http://localhost:8000` | Base da API em links de e-mail e assets; em prod também entra em `CSRF_TRUSTED_ORIGINS` |
| `PUBLIC_SITE_URL` | `http://localhost:4321` | Site público: destino dos redirecionamentos de confirmação/cancelamento e link "acompanhar" |
| `CORS_ALLOWED_ORIGINS` | domínios `www`, apex e `homologacao` de elasnocongresso.com.br + `http://localhost:4321` | CORS restrito a `^/api/.*$` |

### E-mail

| Variável | Padrão | Uso |
| --- | --- | --- |
| `AWS_SES_FROM_EMAIL` | `alertas@elasnocongresso.local` | Remetente; `DEFAULT_FROM_EMAIL` vira `Elas no Congresso <...>` |
| `AWS_DEFAULT_REGION` | `us-east-1` | Região do SES |
| `AWS_SES_ENDPOINT_URL` | `None` | Endpoint alternativo (MiniStack); prod força `None` |
| `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | `None` | Só sem IAM role; em produção a instância usa role |
| `EMAIL_BACKEND`, `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD` | SMTP, `localhost`, `1025`, `False`, vazio, vazio | Apenas `dev` (Mailpit) |

Em base/prod o backend é `anymail.backends.amazon_sesv2`.

### Alertas

| Variável | Padrão | Uso |
| --- | --- | --- |
| `DAILY_DIGEST_TIME` | `09:00` | Corte e disparo do resumo diário (`HH:MM`, São Paulo). Use o mesmo valor no Beat e nos workers e reinicie ambos |
| `SUBSCRIPTION_THROTTLE_RATE_PER_HOUR` | `10` | Limite de `POST /subscriptions/` por IP |
| `SUBSCRIPTION_CONFIRMATION_COOLDOWN_SECONDS` | `300` | Intervalo mínimo entre e-mails de confirmação para o mesmo endereço (429 antes disso) |
| `SUBSCRIPTION_CONFIRMATIONS_PER_DAY` | `3` | Teto diário de confirmações por endereço |

`SUBSCRIPTION_CONFIRM_TTL_HOURS = 48` é constante, sem variável.

### Proteção da API pública

| Variável | Padrão | Uso |
| --- | --- | --- |
| `TRUST_CF_CONNECTING_IP` | base `False`, prod `True` | Identifica o cliente pelo `CF-Connecting-IP`. Só é seguro com a origem alcançável apenas pelo Cloudflare |
| `API_THROTTLE_RATE` | `300/m` | Limite geral por IP para rotas sem limite próprio (test usa `100000/m`) |
| `EXPORT_THROTTLE_RATE` | `20/h` | `GET /activity/explorer/export` por IP |
| `DATASET_DOWNLOAD_THROTTLE_RATE` | `5/h` | `GET /dataset/download` por IP; além disso, um download por vez (503 enquanto outro roda) |
| `NINJA_PAGINATION_MAX_LIMIT` | `1000` | Maior `limit` aceito nas listas paginadas (422 acima) |
| `DATASET_PAGINATION_MAX_LIMIT` | `100` | Maior `limit` de `GET /dataset` |
| `PUBLIC_CACHE_MAX_AGE` / `PUBLIC_CACHE_S_MAXAGE` / `PUBLIC_CACHE_STALE_WHILE_REVALIDATE` | `60` / `300` / `600` | `Cache-Control` das respostas 200 de GET em `/api/v1/` (exceto `/subscriptions/`) |
| `DB_STATEMENT_TIMEOUT_MS` | `0` (deploy: `15000`) | Teto por query, aplicado só pelo processo ASGI; workers e `migrate` ignoram |

Buscas livres (`q`, `search`) aceitam até 200 caracteres e filtros múltiplos do
explorer até 100 valores.

### Ingestão e QuitérIA

| Variável | Padrão | Uso |
| --- | --- | --- |
| `INGESTION_BATCH_SIZE` | `10` | Itens por lote de processamento (≥ 1) |
| `INGESTION_REQUESTS_PER_SECOND` | `2.0` | Limite por host compartilhado via Redis (≥ 0; test usa 0) |
| `INGESTION_RECONCILIATION_DAILY_LIMIT` | `600` | Proposições reconciliadas por casa por dia (≥ 1) |
| `CLASSIFICATION_BACKFILL_DAILY_LIMIT` | `600` | Lacunas de avaliação enfileiradas por dia (≥ 1) |
| `TSE_CANDIDATES_ARCHIVE_URLS` | JSON com arquivos de candidaturas 2018 e 2022 | Enriquecimento TSE |
| `QUITERIA_ENABLED` | `True` | Liga a classificação (test usa `False`) |
| `QUITERIA_MODEL_DIR` | `/models/quiteria-2.0` | Diretório dos pesos |
| `QUITERIA_FAVORABILITY_THRESHOLD` | `0.2254` | Limiar da classe desfavorável |

Constantes sem variável: `QUITERIA_MODEL_ID="azmina/quiteria-2.0"`,
`QUITERIA_MODEL_REVISION` (também fixada no `Dockerfile`) e os limites
`SENADO_FRONT_*` do raspador de frentes. A imagem define `TESSERACT_CMD` e
`TESSDATA_PREFIX`.

### Newsletter semanal

| Variável | Padrão | Uso |
| --- | --- | --- |
| `WEEKLY_NEWSLETTER_ENABLED` | `False` | Registra as quatro tarefas de segunda-feira no Beat e libera as tarefas automáticas |
| `WEEKLY_NEWSLETTER_BATCH_SIZE` | `5` | Lote do `--refresh` (≥ 1) |
| `SUBSTACK_PUBLICATION_URL` | `https://elasnocongresso.substack.com` | Origem HTTPS da publicação, sem caminho |
| `SUBSTACK_COOKIES_STRING` | vazio | Cabeçalho `Cookie` completo de uma sessão autorizada; segredo |

### Observabilidade

| Variável | Padrão | Uso |
| --- | --- | --- |
| `ACTIVITY_EXPLORER_TRACE_SAMPLE_RATE` | `0.0` | Fração (0–1) de requisições do explorer com trace estruturado |
| `SECURE_SSL_REDIRECT` | `True` | Apenas prod |

## Diferenças entre ambientes

| Aspecto | dev | prod | test |
| --- | --- | --- | --- |
| `DEBUG` | `True` | `False` | `False` |
| E-mail | SMTP → Mailpit | SES v2 | SES apontado para `localhost:4566` |
| Cache | Redis | Redis | LocMem |
| Celery | broker Redis | broker Redis | *eager*, propaga exceções |
| QuitérIA | conforme env | conforme env | desligada |
| Extras | `admindocs` | HSTS 1 ano com preload, cookies seguros, `X_FRAME_OPTIONS=DENY`, `CONN_HEALTH_CHECKS`, proxy SSL header, `/health/` isento de redirect | hasher MD5 |

## Valores fixos relevantes

- `LANGUAGE_CODE="pt-br"`, `TIME_ZONE="America/Sao_Paulo"`, `CELERY_TIMEZONE` idem.
- Cache padrão com `TIMEOUT=300`; endpoints de atividade usam 5 minutos.
- Celery: `acks_late`, `prefetch_multiplier=1`, compressão gzip,
  `visibility_timeout` de 6 h, para que tarefas longas não sejam reentregues.
- Validações na carga das configurações: limites ≥ 1, taxa ≥ 0 e taxa de trace
  entre 0 e 1. Valores inválidos impedem a inicialização.
