# Desenvolvimento local

## Pré-requisitos

- Docker e Docker Compose (o `Makefile` usa `docker-compose`).
- [uv](https://github.com/astral-sh/uv) com Python 3.12 (`.python-version`).
- Node.js LTS, apenas para compilar os templates de e-mail fora do Docker
  (`mise.toml` declara `node = "lts"`).

## Primeira execução

```bash
cp .env.example .env
uv sync
make up        # postgres, redis, mailpit, ministack, api, worker, ml-worker, beat
make migrate   # opcional: o serviço api já executa migrate ao iniciar
make seed      # carrega fixtures/seed.json
open http://localhost:8000/api/v1/docs
```

O `.env.example` aponta para as portas publicadas pelo Compose (`5432` e
`6379`), então Django no host (`uv run ./manage.py ...`) usa os mesmos
containers. Dentro do Compose, o `environment` de cada serviço tem precedência.

### Serviços do Compose

| Serviço | Imagem/comando | Porta no host |
| --- | --- | --- |
| `postgres` | `pgvector/pgvector:pg16` | 5432 |
| `redis` | `redis:7-alpine` | 6379 |
| `mailpit` | `axllent/mailpit:v1.26` (SMTP do ambiente dev) | 1025 (SMTP), 8025 (UI) |
| `ministack` | mock de SES, inicializado por `ops/ministack/bootstrap.sh` | 127.0.0.1:4566 |
| `api` | `python scripts/start_api.py` (migrate + uvicorn) | 8000 |
| `worker` | `celery worker -Q celery --concurrency=2` | — |
| `ml-worker` | `celery worker -Q ml --concurrency=1` | — |
| `beat` | `celery beat --scheduler DatabaseScheduler` | — |

Em `dev`, e-mails vão por SMTP para o Mailpit (`http://localhost:8025`).
O MiniStack cria as identidades SES `alerts@` e `newsletter@elasnocongresso.local`
e é usado pelos testes de integração de envio.

A imagem é distroless, sem shell nem dependências de desenvolvimento. Comandos
de gerenciamento funcionam com `docker compose exec api python manage.py ...`;
testes, lint e scripts rodam no host com `uv run`.

### Usuário do admin

```bash
uv run ./manage.py createsuperuser
# ou, dentro do container
docker compose exec api python manage.py createsuperuser
```

O admin fica em `http://localhost:8000/admin/` (configurável por `ADMIN_URL`).

### Dados de desenvolvimento

- `make seed` carrega `fixtures/seed.json`: 2 legislaturas, 9 partidos,
  10 temas, 5 etiquetas analíticas e 5 comissões.
- Para dados reais, rode a ingestão: `python manage.py ingestion_sync --mode bootstrap`
  (ver [ingestao.md](ingestao.md)). As proposições entram com `is_approved=False`
  e só aparecem na API pública depois de aprovadas no admin.

### QuitérIA localmente

`QUITERIA_ENABLED=True` é o padrão, mas os pesos (~870 MB) só existem na imagem
Docker, em `/models/quiteria-2.0`. Ao rodar workers no host, defina
`QUITERIA_ENABLED=False` ou baixe os artefatos para `QUITERIA_MODEL_DIR` com a
mesma revisão do `Dockerfile`.

### Templates de e-mail

```bash
npm install --prefix apps/subscriptions/emails
npm run build --prefix apps/subscriptions/emails
```

O HTML vai para `apps/subscriptions/emails/dist/` (não versionado). Detalhes em
[`apps/subscriptions/emails/README.md`](../apps/subscriptions/emails/README.md).

## Testes

Configuração em `pyproject.toml`: `DJANGO_SETTINGS_MODULE=config.settings.test`,
`asyncio_mode=auto`. As configurações de teste usam Celery *eager*, cache
LocMem, `QUITERIA_ENABLED=False` e limite de requisições zerado.

Os testes precisam de PostgreSQL (há uso de `unaccent` e pgvector). O banco
padrão é `legislativo_test` em `POSTGRES_HOST:POSTGRES_PORT` com `elas/elas`;
`TEST_DATABASE_URL` substitui essa conexão. Redis não é necessário.

| Comando | Escopo |
| --- | --- |
| `make test` | `tests/unit/` e `apps/*/tests/` |
| `make test-integration` | `tests/integration/ --reuse-db` |
| `uv run pytest` | Tudo, exceto `tests/load` (ignorado pelo pytest) |
| `make loadtest` | Locust contra `http://localhost:8000` |

Organização:

- `tests/unit/`: compilador de critérios, schemas, extração de texto e
  desempenho do explorer.
- `tests/integration/`: APIs, explorer, inscrições, entrega de alertas, filtros
  por casa, tarefas e o fluxo ingestão → alerta.
- `apps/ingestion/tests/`: clientes, mapeadores, resolvedores, relevância,
  sincronização diária, versões de conteúdo, OCR, TSE, frentes, backfill.
  `fixtures/*.json` traz respostas reais das fontes.
- `apps/newsletters/tests/`: relatório, cobertura, entrega e concorrência.
- `apps/legislatures/tests/`, `apps/propositions/tests/`, `apps/committees/tests/`.

Fixtures úteis: `daily_clock` (congela 06/10/2026 08:00 em São Paulo),
`outbox`, `ministack_container`/`ses_client` (testcontainers) em
`tests/integration/conftest.py`; `camara_payload`/`senado_payload` em
`apps/ingestion/tests/conftest.py`. O `tests/conftest.py` raiz só aponta o
testcontainers para o socket do OrbStack quando ele existe.

As settings de teste usam `StaticFilesStorage`, então os testes do admin não
dependem de `collectstatic`.

## Qualidade de código

```bash
make lint   # ruff check . && mypy .
```

Ruff: linha de 100 colunas, regras E, F, I, UP, B e SIM (`ruff.toml`).
mypy usa `django-stubs`.

## Diagnóstico

- `python manage.py profile_activity_explorer --query "house=camara" --runs 3`
  executa o explorer pelo pipeline real (`django.test.Client`) e imprime JSON
  com etapas e SQL. `--bypass-cache` reconstrói a fonte sem tocar o cache
  compartilhado; `--profile arquivo.prof` gera cProfile (exige `--runs 1`).
- `ACTIVITY_EXPLORER_TRACE_SAMPLE_RATE` (0 a 1) amostra traces estruturados do
  explorer em produção e adiciona `X-Explorer-Trace-ID`.
- `uv run python scripts/smoke_ingestion.py --days 3` consulta as APIs reais sem
  banco e grava fixtures em `apps/ingestion/tests/fixtures/`.

## Scripts avulsos

| Script | Uso |
| --- | --- |
| `scripts/start_api.py` | Entrypoint do `api` no Compose: `migrate --noinput` e `exec` do uvicorn em `$PORT` |
| `scripts/smoke_ingestion.py` | Smoke test das fontes, sem banco |

O banco é a referência dos dados. As cargas históricas por planilha já foram
aplicadas e seus scripts foram removidos.
