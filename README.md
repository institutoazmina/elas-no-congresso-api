# Elas no Congresso API

API Django para acompanhamento de proposições legislativas do Congresso Brasileiro.

## Sobre

Projeto do [Instituto AzMina](https://azmina.org.br) em parceria com o Programa QuitérIA — usando dados abertos da Câmara dos Deputados e Senado Federal.

## Arquitetura

```
┌─────────────┐     ┌──────────┐     ┌─────────────┐
│  API Ninja  │────▶│ Postgres │◀────│  Celery    │
│ (uvicorn)   │     │ +vector  │     │  Worker   │
└─────────────┘     └──────────┘     └─────┬─────┘
       │                 ▲                 │
       │                 │                 ▼
       ▼            ┌──────┐          ┌──────────┐
    /api/v1/        │ Redis │          │ MiniStack │
                    └──────┘          │  (SES)   │
                                       └──────────┘
```

## Pré-requisitos

- Docker + Docker Compose
- Python 3.12 (via [uv](https://github.com/astral-sh/uv))

## Setup Local

```bash
# Criar .env baseado em .env.example
cp .env.example .env

# Subir serviços (postgres, redis, ministack, api, worker, beat)
make up

# Rodar migrações
make migrate

# (Opcional) Popular dados sintéticos
make seed

# Acessar API docs
open http://localhost:8000/api/v1/docs
```

## Endpoints Principais

| Método | Camino | Descrição |
|--------|--------|-----------|
| GET | /api/v1/propositions | Lista proposições (paginado) |
| GET | /api/v1/propositions/{id} | Detalhes de proposição |
| GET | /api/v1/parliamentarians | Lista parlamentares |
| GET | /api/v1/themes |Lista de temas |
| GET | /api/v1/parties | Lista de partidos |
| GET | /api/v1/committees | Lista de comissões |
| POST | /api/v1/subscriptions | Criar inscrição |
| POST | /api/v1/subscriptions/confirm/{token} | Confirmar inscrição |
| DELETE | /api/v1/subscriptions/unsubscribe/{token} | Cancelar inscrição |

Documentação completa em `/api/v1/docs`.

## Admin

- Django Admin: `http://localhost:8000/admin/` (usar sessão Django)

### Criar Admin

```bash
# Via container Docker
docker compose exec api python manage.py createsuperuser --username admin --email admin@elas.gov.br --noinput
docker compose exec api python manage.py shell -c "from django.contrib.auth import get_user_model; u = get_user_model().objects.get(username='admin'); u.set_password('admin123'); u.save()"

# Ou localmente
uv run ./manage.py createsuperuser --username admin
uv run ./manage.py shell -c "from django.contrib.auth import get_user_model; u = get_user_model().objects.get(username='admin'); u.set_password('admin123'); u.save()"
```

Login padrão: `admin` / `admin123`

## Desenvolvimento

```bash
# Sync dependências
uv sync

# Lint
make lint  # ou: ruff check .

# Testes unitários
make test

# Testes de integração
make test-integration

# Testes de carga
make loadtest

# shell Django
uv run ./manage.py shell
```

## Deploy

Variáveis obrigatórias:

- `SECRET_KEY` — chave secreta Django
- `DEBUG=False` — modo produção
- `DATABASE_URL` — conexão PostgreSQL
- `REDIS_URL` — conexão Redis
- `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` — credenciais AWS
- `AWS_SES_FROM_EMAIL` — e-mail verificado no SES

### SES Produção

1. Sair do [sandbox SES](https://docs.aws.amazon.com/ses/latest/developer-guide/sandbox.html)
2. Configurar `SES_CONFIGURATION_SET` para tracking
3. Ajustar `AWS_SES_ENDPOINT_URL` para `None` em produção

## Performance

 benchmmarks Targets:
- Matcher: p95 < 30ms (10k subscriptions × 900 propositions)
- API GET /propositions: p95 < 200ms sustentando 500 rps
- DB: índices GIN/HNSW/trigram, connection pooling

## Licença

AGPL-3.0 — Instituto AzMina