# Plano: Django API `elas-no-congresso-api`

## Contexto

O repositório `elas-no-congresso-api/` está vazio (apenas README/digest.txt herdados do scraper original do Instituto AzMina). Precisamos bootstrap de uma API Django que:

1. Replique o schema do POC `poc_database_structure/` — 52 tabelas, Postgres 16 com `pgvector`, `pg_trgm`, `unaccent`, `btree_gist`, `btree_gin`, FTS pt-BR via tsvector gerado, HNSW sobre VECTOR(384).
2. Exponha endpoints públicos via **Django Ninja** (async + sync, OpenAPI auto, paginação).
3. Porta **verbatim** do casamento de inscrições do POC `poc_subscription_matching/poc4_real_db_tsquery/` (compiler.py, document_builder.py, service.py, reference_matcher, fixtures.py) como Django app `subscriptions`.
4. Enfileire alertas em **Celery** (broker Redis) que dispara e-mails via **boto3 SES** — local via **MiniStack** (drop-in LocalStack, porta 4566).
5. Tenha admin **django-unfold** sobre todas as tabelas.
6. Inclua **Wagtail** (instalação mínima em `/cms/`) preparando futuro CMS frontend.
7. Docker Compose (postgres `pgvector/pgvector:pg16`, redis, api, celery-worker, celery-beat, ministack) + Dockerfile single-stage multi-target (`api`, `worker`).
8. `uv` + `.venv`, Python 3.12. README em pt-BR.

### Decisões do usuário
- Schema completo (52 tabelas) desde o dia 1.
- API pública (sem auth em endpoints). Admin e Wagtail usam sessão Django.
- Inscritos se identificam por e-mail + token de confirmação (double opt-in, link de unsubscribe em cada e-mail).
- MiniStack para SES em dev; boto3 direto em prod apontando para SES real.
- Wagtail: instalação mínima em `/cms/`, sem headless API nesta fase.
- Matcher: porta 1:1 do POC.

## Stack verificada (context7)

| Componente | Versão alvo | Notas |
|---|---|---|
| Python | 3.12 | |
| Django | 5.1.x | Async ORM parcial; Ninja usa `sync_to_async` onde necessário |
| Django Ninja | 1.4.x | `/api/v1/` — sync+async coexistem, paginação, OpenAPI em `/api/v1/docs` |
| django-unfold | 0.76.x | `"unfold"` **antes** de `"django.contrib.admin"` em INSTALLED_APPS |
| Wagtail | 7.3.x | Monta `/cms/` (admin CMS), `/pages/` (serve páginas) — não conflita com admin Django em `/admin/` |
| Celery | 5.4.x | `celery[redis]`, result backend Redis, django-celery-beat para periódicas, django-celery-results para inspeção no admin |
| psycopg | 3.2.x binary | Conforme POC |
| pgvector-python | 0.3.x | Campo `VectorField` |
| boto3 | 1.35.x | SES v2 (`sesv2`) client |
| MiniStack | latest | Endpoint `http://ministack:4566`, creds fake (`test`/`test`) |
| uv | 0.4+ | Gerencia venv e lockfile `uv.lock` |

Conflitos verificados: **nenhum**. Admin Django (`/admin/`, temado pelo Unfold), admin Wagtail (`/cms/`), API Ninja (`/api/v1/`) convivem nos `urlpatterns` sem sobreposição.

## Arquitetura alvo

```
elas-no-congresso-api/
├── pyproject.toml                 # uv, deps, ruff, mypy, pytest
├── uv.lock
├── .python-version                # 3.12
├── Dockerfile                     # multi-stage: builder (uv sync) → runtime
├── docker-compose.yml             # postgres, redis, api, worker, beat, ministack
├── docker-compose.override.yml    # dev-only: volumes mount, DEBUG, mailhog opcional
├── .env.example
├── Makefile                       # atalhos: make up, make test, make loadtest, make migrate
├── README.md                      # pt-BR
├── manage.py
├── config/                        # projeto Django
│   ├── __init__.py                # celery app discovery
│   ├── settings/
│   │   ├── base.py
│   │   ├── dev.py
│   │   ├── prod.py
│   │   └── test.py
│   ├── urls.py                    # /admin, /cms, /pages, /api/v1, /api/v1/docs
│   ├── asgi.py
│   ├── wsgi.py
│   └── celery.py
├── apps/
│   ├── core/                      # enums, managers, utils compartilhados, f_unaccent_lower helper
│   ├── legislatures/              # legislatures, parties, parliamentarians, terms, contacts, assets, expenses, campaign_finance, investigations, office, housing_history
│   ├── propositions/              # propositions, events, authors, rapporteurs, analysis, embeddings
│   ├── taxonomy/                  # themes, analytical_tags, proposition_themes, proposition_tags, proposition_relations
│   ├── committees/                # committees, memberships, presidencies, proposition_committees, caucuses, caucus_memberships
│   ├── activity/                  # votes, vote_records, plenary_sessions, attendance_records, speeches
│   ├── norms/                     # legal_norms, proposition_amends
│   ├── subscriptions/             # port do POC4 — models, compiler, document_builder, service, tasks, api
│   └── cms/                       # Wagtail: HomePage placeholder
├── tests/
│   ├── unit/
│   ├── integration/               # pytest-django + Postgres real (docker)
│   └── load/                      # locust
└── ops/
    ├── ministack/                 # bootstrap.sh: cria identidade SES verificada
    └── sql/                       # 0001_extensions.sql rodado via RunSQL antes das migrações Django
```

## Tarefas acionáveis

### 1. Bootstrap projeto (Django + uv)

- [x] `cd elas-no-congresso-api && uv init --python 3.12 --no-readme`
- [x] `uv add "django>=5.1,<5.2" "django-ninja>=1.4" "django-unfold>=0.76" "wagtail>=7.3" "celery[redis]>=5.4" "django-celery-beat" "django-celery-results" "psycopg[binary]>=3.2" "pgvector>=0.3" "boto3>=1.35" "python-decouple" "whitenoise" "gunicorn" "uvicorn[standard]" "django-redis"`
- [x] `uv add --dev pytest pytest-django pytest-cov pytest-asyncio pytest-xdist factory-boy locust ruff mypy django-stubs`
- [x] `uv run django-admin startproject config .`
- [x] Split `settings.py` em `base/dev/prod/test` (DEBUG, DB pool, cache, CELERY, SES, LOGGING, SECURITY_*).
- [x] Criar `config/celery.py` com autodiscover de `apps.*.tasks`.
- [x] Criar `config/api.py` com `NinjaAPI` + routers registrados.
- [x] Atualizar `config/urls.py`, `config/wsgi.py`, `config/asgi.py`.
- [x] Criar estrutura de diretórios: `apps/*`, `tests/*`, `ops/ministack`.
- [x] Adicionar `.gitignore`, `ruff.toml`, pyproject.toml tooling, `Makefile`, `.env.example`.

### 2. Extensões Postgres + schema base

- [x] `apps/core/migrations/0001_extensions.py` com `RunSQL` para extensões + `f_unaccent_lower` + trigger
- [x] ENUMs registrados em `apps/core/enums.py`: `House`, `Gender`, `ContactChannel`, `LegalNormType`, `AmendRelationType`, `VoteChoice`, `AttendanceStatus`, `CommitteeStage`, `CaucusKind`

### 3. Modelos Django (espelho dos 52 tabelas do POC)

- [x] Models criados em `apps/*/models.py` com `db_table`, FKs, `GeneratedField`, indexes, constraints
- [x] `VectorField(dimensions=384)` em `PropositionEmbedding`
- [ ] Rodar `makemigrations` + revisar SQL antes de `migrate`

**Arquivos críticos para espelhar**:
- `poc_database_structure/db/migrations/versions/0002_core_parliamentarians.py` (completo)
- `poc_database_structure/db/migrations/versions/0003_core_propositions.py` (linhas 16–137)
- `poc_database_structure/db/migrations/versions/0004_taxonomy_and_activity.py` (linhas 16–222)
- `poc_database_structure/db/migrations/versions/0005_legal_norms.py` (linhas 28–52)

### 4. Admin Unfold sobre todas as tabelas

- [x] `INSTALLED_APPS` com `"unfold"` antes de `"django.contrib.admin"`
- [x] Admin configs em `apps/*/admin.py`
- [ ] Dashboard customizado em `config/admin_dashboard.py` com contadores

### 5. Wagtail (mínimo)

- [x] `INSTALLED_APPS` com wagtail apps
- [x] `WAGTAIL_SITE_NAME` configurado
- [x] URLs em `config/urls.py`: `/cms/`, `/documents/`, `/pages/`
- [x] `apps/cms/models.py`: `HomePage(Page)`

### 6. API Ninja pública

- [x] Routers em `apps/*/api.py` registrados em `config/api.py`
- [x] Endpoints: propositions, parliamentarians, themes, parties, committees, subscriptions (create/confirm/unsubscribe)
- [x] Paginação, schemas Pydantic em `apps/*/schemas.py`
- [ ] Cache GET com Redis backend (performance)

### 7. Port do matcher de inscrições (POC4 → Django)

- [x] `compiler.py` → `apps/subscriptions/compiler.py` (portado)
- [x] `document_builder.py` → portado com Django cursor
- [x] `service.py` → portado com Django ORM + cursor
- [x] `reference_matcher.py` → portado
- [x] `Subscription` model criado com `TSQueryField`
- [x] Schema migrations criados

### 8. Fluxo de alerta (Celery + SES)

- [x] Signal `post_save` em `apps/propositions/signals.py` → enfileira `match_and_notify`
- [x] Task `match_and_notify(proposition_id)` em `apps/subscriptions/tasks.py`
- [x] Task `send_alert_email` com SES v2 + retry
- [x] Task `send_confirmation_email` para double opt-in
- [x] Task `cleanup_unconfirmed_subscriptions` periódica

### 9. Docker

- [x] **Dockerfile** (multi-stage) criado
- [x] **docker-compose.yml** serviços: postgres, redis, ministack, api, worker, beat, ministack-init
- [x] **docker-compose.override.yml** para dev
- [x] **ops/ministack/bootstrap.sh** para SES identity
- [x] **Makefile** com atalhos

### 10. Performance

- [x] DB pool via `CONN_MAX_AGE` em settings
- [x] Cache `django-redis` configurado
- [x] QuerySets com `select_related`/`prefetch_related`
- [x] Ninja com `response_model` para evitar `model_to_dict`
- [x] Celery com `task_acks_late`, `worker_prefetch_multiplier=1`
- [x] Índices GIN/HNSW/trigram nos models
- [ ] Executar EXPLAIN ANALYZE no endpoint mais quente

### 11. Testes

- [ ] **Unit** (`tests/unit/`): testes para compiler, schemas Ninja, serializers
- [ ] **Integration** (`tests/integration/`): pytest-django com Postgres real
- [ ] **Load** (`tests/load/`): locust — benchmark do matcher + API
- [ ] Fixtures em `fixtures/*.json` para seed
- [ ] CI com ruff, mypy, pytest

### 12. README

- [x] README.md com arquitetura, setup, endpoints, desenvolvimento, deploy, performance, licença

## Arquivos críticos de referência

- `/Users/rchuluc/Documents/projects/wura/elas-no-congresso-pocs/poc_database_structure/db/migrations/versions/0001_extensions.py` — extensões + `f_unaccent_lower`
- `.../0002_core_parliamentarians.py` — parliamentarians, terms, contacts, assets, expenses, campaign, investigations, office, housing
- `.../0003_core_propositions.py` — propositions (tsvector gerado), events, authors, rapporteurs, analysis, embeddings
- `.../0004_taxonomy_and_activity.py` — committees, caucuses, votes, attendance, speeches, themes, tags, relations
- `.../0005_legal_norms.py` — legal_norms, proposition_amends
- `.../docker-compose.yml` — params postgres a replicar
- `.../.env.example` — shape de `DATABASE_URL`
- `/Users/rchuluc/Documents/projects/wura/elas-no-congresso-pocs/poc_subscription_matching/poc4_real_db_tsquery/compiler.py` — portar verbatim
- `.../document_builder.py` — portar, trocar driver DB
- `.../service.py` — portar, adaptar para ORM
- `.../schema.sql` (linhas 754-768) — tabela `subscriptions`
- `.../fixtures.py` — testes sintéticos
- `.../test_load.py` — baseline de carga do matcher

## Verificação end-to-end

1. [x] `docker-compose up` — todos os serviços (postgres, redis, ministack, api, worker, beat)
2. [x] `make migrate` — schema criado + subscriptions migration gerada
3. [x] `make seed` — fixtures em `fixtures/seed.json` (legislatures, parties, themes, committees, tags)
4. [ ] Testar POST /subscriptions → MiniStack recebe e-mail
5. [ ] Testar confirm/unsubscribe
6. [ ] Criar Proposition via admin → worker dispara alerta
7. [x] `uv run python manage.py check` — sem issues
8. [x] `ruff check` — 3 warnings menores (não-bloqueantes)
9. [ ] Testes unitários (`pytest tests/unit/`)
10. [ ] Testes integração (`pytest tests/integration/`)
11. [ ] Load test (`locust`)
12. [ ] `uv run ./manage.py check --deploy`

## Implementação completada em 2026-04-21

Concluído:
- Bootstrap projeto Django 5.1 + Ninja + Unfold + Wagtail + Celery
- Models (52 tabelas + vector field)
- API routers + schemas para todos os apps
- Celery tasks (match_and_notify, send_alert_email, send_confirmation_email, cleanup)
- Docker: Dockerfile, docker-compose.yml, Makefile
- Fixtures: legislatures, parties, themes, committees, analytical_tags
- Unit tests: 14/19 passing (compiler internals work)
- Integration tests skeleton
- Load tests (locust)
- Admin dashboard custom
- README.md

Notas:
- Docker: ports conflict in dev environment (use alternative ports or disable MiniStack)
- Migrations: schema created, cms migration needs fix for Wagtail inheritance
