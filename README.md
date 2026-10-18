# Elas no Congresso API

API Django para acompanhamento de proposições legislativas do Congresso Brasileiro.

## Sobre

O [Elas no Congresso](https://elasnocongresso.com.br) é um projeto do [Instituto AzMina](https://institutoazmina.org.br) que monitora as pautas de gênero no Congresso Nacional usando dados abertos da Câmara dos Deputados e Senado Federal.

A [QuitérIA](https://github.com/institutoazmina/ia-feminista-elas-no-congresso) é a ferramenta de inteligência artificial feminista responsável por classificar os temas e a favorabilidade das proposições legislativas monitoradas.

## Arquitetura

```mermaid
flowchart LR
    API[API Django Ninja] --> DB[(PostgreSQL)]
    API --> R[(Redis: cache e broker)]
    B[Celery Beat] --> R
    R --> W[Workers Celery]
    W --> DB
    W --> S[Amazon SES ou MiniStack local]
    W --> M[QuitérIA local na fila ML]
    W --> D[Substack: somente rascunhos]
```

As [decisões de arquitetura](docs/README.md) documentam a estrutura do banco,
os alertas, os rascunhos do Substack e a ingestão com análise local de IA.

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

## Alertas diários

Os matches de inscrições diárias ficam em uma fila persistida até o resumo.
O Celery Beat dispara às **09:00 de America/Sao_Paulo** por padrão. Configure
`DAILY_DIGEST_TIME=HH:MM` no ambiente do beat e dos workers e reinicie ambos
para alterar o horário. Aplique as migrações antes de iniciar os novos workers.

Cada endereço recebe no máximo um resumo diário, mesmo com várias inscrições.
O conteúdo é agrupado por tema editorial e, dentro do tema, pela celeridade
calculada a partir do histórico oficial. Anotações humanas prevalecem sobre a
análise concluída da QuitérIA; itens sem categoria têm uma seção própria.
Matches posteriores ao horário de corte entram no próximo dia. Não há envio
sem novidades; pendências de dias anteriores são preservadas e revalidadas
antes de enviar. Falhas de envio mantêm as pendências para retry.

A proteção por endereço/data serializa tarefas concorrentes e repetidas.
Como SES e PostgreSQL não compartilham uma transação, uma interrupção do worker
depois da aceitação pelo SES e antes do commit ainda pode causar reenvio.
O template e o envio semanal foram retirados. A migração `0006` desativa
agendamentos semanais persistidos no banco do Celery Beat; tarefas antigas
já presentes no broker são descartadas sem enviar e-mails.

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

### CI nos Pull Requests

O workflow [CI](.github/workflows/ci.yml) roda em todos os Pull Requests,
manualmente pelo GitHub Actions e como pré-requisito do deploy de `main`.
O job `Lint, migrations and tests` verifica o lockfile (`uv sync --locked`), compila
os templates MJML, executa Ruff, os checks do Django, a detecção de migrações
pendentes e os testes em `tests/unit/`, `apps/`, `tests/integration/` e
`tests/compatibility/` (exceto inferência real, executada em job separado).
O pytest cria um banco novo e aplica todas as migrações.

O ambiente usa Python de `.python-version`, Node 22 e PostgreSQL 16 com pgvector.
Os testes de SES iniciam MiniStack via testcontainers; Celery roda em modo eager
e o cache fica em memória. O CI instala Tesseract com dados de português para
validar OCR real. Não são necessários secrets de produção nem Redis.
O job `Quiteria model compatibility` baixa e mantém em cache a revisão fixa dos
pesos, confere seus hashes e executa inferência CPU offline contra um baseline
anterior aos upgrades. Os testes de carga continuam sendo executados separadamente
com `make loadtest`.

Os relatórios JUnit e de cobertura ficam no artefato `test-reports` por 14 dias,
inclusive quando há falhas nos testes. A cobertura é informativa, sem mínimo
obrigatório. Novos commits cancelam a execução anterior do mesmo PR.

O check final `CI passed` exige sucesso dos testes, da inferência real e dos jobs de segurança.
O ruleset de `main` exige esse check e atualização em relação à branch base.
O deploy, tanto por push em `main` quanto manual, executa o mesmo CI antes de
acessar os secrets de produção. Deploys manuais de outras branches são ignorados.

O [workflow de segurança](.github/workflows/security.yml) inclui CodeQL para
Python e GitHub Actions, auditoria das dependências Python e npm e varredura de
secrets no histórico Git com Gitleaks. Também roda semanalmente. Consulte
[segurança no CI](docs/security-ci.md) para os limites, comandos e pendências
encontradas na configuração inicial.

O Renovate propõe atualizações semanais de dependências, mantendo Django e o
runtime de IA sob revisão separada. Veja a [política de atualizações](docs/dependency-updates.md).
Os [testes de compatibilidade](docs/dependency-compatibility-tests.md) descrevem
as garantias, os limites e como reproduzir o baseline antes de atualizar pacotes.

Para reproduzir a suíte completa localmente, com Docker disponível:

```bash
uv sync --locked --dev
# Instalar Tesseract e o idioma português no sistema; em Ubuntu/Debian:
sudo apt-get install tesseract-ocr tesseract-ocr-por
docker compose up -d postgres
npm ci --prefix apps/subscriptions/emails
npm run build --prefix apps/subscriptions/emails
DJANGO_SETTINGS_MODULE=config.settings.test uv run python manage.py check
DJANGO_SETTINGS_MODULE=config.settings.test uv run python manage.py makemigrations --check --dry-run
uv run ruff check .
DJANGO_SETTINGS_MODULE=config.settings.test uv run pytest -m "not ml" --cov=apps --cov=config
```

Se o PostgreSQL estiver em outra porta ou usar outras credenciais, configure
`TEST_DATABASE_URL=postgresql://usuario:senha@localhost:porta/banco`. O usuário
precisa poder criar bancos de teste e as extensões usadas pelas migrações.

## Deploy

O [Radar semanal no Substack](docs/decisions/001-weekly-substack-drafts.md) prepara rascunhos para revisão
humana, com LEGENDA, destaques e Radars por casa. Está desativado por padrão e
nunca publica ou envia e-mails.

Variáveis obrigatórias:

- `SECRET_KEY` — chave secreta Django
- `DEBUG=False` — modo produção
- `DATABASE_URL` — conexão PostgreSQL
- `REDIS_URL` — conexão Redis
- `AWS_SES_FROM_EMAIL` — e-mail verificado no SES

### SES Produção

1. Sair do [sandbox SES](https://docs.aws.amazon.com/ses/latest/developer-guide/sandbox.html)
2. Configurar `SES_CONFIGURATION_SET` para tracking
3. Em produção no EC2, associar uma instance role com `ses:SendEmail` e
   `ses:SendRawEmail` à identidade SES verificada. O Boto3 obtém e renova as
   credenciais temporárias automaticamente; não configure access keys estáticas.
4. Ajustar `AWS_SES_ENDPOINT_URL` para `None` em produção

## Performance

A [ADR da estrutura do banco](docs/decisions/004-estrutura-do-banco.md) descreve
a projeção de leitura e os limites do cache do explorer. O comando
`python manage.py profile_activity_explorer` continua disponível para diagnóstico;
suas medições não equivalem à latência de rede ou a um teste de carga.

## Licença

AGPL-3.0 — Instituto AzMina
