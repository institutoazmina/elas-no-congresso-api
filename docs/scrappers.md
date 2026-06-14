# Raspadores (Ingestion)

Coleta automática de proposições legislativas da **Câmara dos Deputados** e do
**Senado Federal**, com foco em pautas de gênero/direitos das mulheres. Substitui
o `elasnocongressobot` (Scrapy + CSV + Google Sheets) por clients HTTP + tasks
Celery gravando direto no domínio relacional (Postgres é a fonte da verdade).

App: [`apps/ingestion/`](../apps/ingestion).

---

## Sumário

- [Arquitetura](#arquitetura)
- [Fluxo da coleta](#fluxo-da-coleta)
- [URLs dos raspadores](#urls-dos-raspadores)
- [Horários (agendamento)](#horários-agendamento)
- [Filtro de tema (`theme_assert`)](#filtro-de-tema-theme_assert)
- [Extração do inteiro teor (PDF)](#extração-do-inteiro-teor-pdf)
- [Persistência e idempotência](#persistência-e-idempotência)
- [Como rodar](#como-rodar)

---

## Arquitetura

```
apps/ingestion/
├── clients/
│   ├── base.py      # httpx keep-alive + retry exponencial (tenacity)
│   ├── camara.py    # Dados Abertos Câmara (JSON)
│   └── senado.py    # Dados Abertos Senado (JSON)
├── theme_assert.py  # filtro de relevância (regex de gênero) — antecipado
├── mappers.py       # payload bruto → kwargs de Proposition/Event/Author/Theme
├── resolvers.py     # autor → Parliamentarian | InstitutionalAuthor (+ sexo)
├── fulltext.py      # download + extração de texto do PDF (inteiro teor)
├── tasks.py         # orquestração Celery (ingest_camara / ingest_senado / classify)
├── models.py        # IngestionRun (auditoria de cada execução)
└── admin.py         # IngestionRun read-only (Unfold)
```

Decisões de projeto:

- **Sem Scrapy**: os "spiders" eram só 2–3 GETs encadeados em APIs REST/XML
  oficiais. Trocados por `httpx` + JSON dentro de tasks Celery — zero dependência
  de peso.
- **Postgres como fonte da verdade** (Google Sheets descontinuado).
- **ML desacoplado da coleta**: a coleta grava `Proposition`; um signal enfileira
  `classify_proposition`. Falha de ML não bloqueia ingestão. Hoje a classificação
  é um stub (loga) que já baixa/extrai o inteiro teor — a inferência em si está
  pendente de decisão (HF endpoint / fila dedicada / local).
- **Filtro de tema antes dos saltos caros**: só descemos em detalhe/autores/textos
  para proposições relevantes.

```mermaid
graph LR
    Beat[Celery Beat] -->|06:00| C[ingest_camara]
    Beat -->|06:10| S[ingest_senado]
    C --> CC[CamaraClient<br/>httpx+JSON]
    S --> SC[SenadoClient<br/>httpx+JSON]
    CC --> API1[(dadosabertos.camara)]
    SC --> API2[(legis.senado dadosabertos)]
    C --> P[(Postgres)]
    S --> P
    C -.->|signal post_save| CL[classify_proposition]
    S -.->|signal post_save| CL
    CL --> PDF[fulltext.extract_pdf_text]
    C -.->|post_save| MN[match_and_notify<br/>alertas e-mail]
    P --> RUN[(IngestionRun<br/>auditoria)]
```

---

## Fluxo da coleta

Cada casa roda em uma task independente (paralelas). O filtro de tema é aplicado
**antes** de qualquer salto caro.

```mermaid
flowchart TD
    A[ingest_camara / ingest_senado] --> B[Cria IngestionRun status=running]
    B --> C[Lista proposições da janela diária]
    C --> D{Para cada item}
    D --> E[assert_theme na ementa]
    E -->|irrelevante| D
    E -->|relevante| F[fetch_detail]
    F --> G[fetch_authors / autoria]
    G --> H[Câmara: fetch_deputy por autor<br/>sexo + partido + UF]
    G --> I[Senado: autoria já traz<br/>sexo + partido + UF]
    F --> J[fetch_texts → inteiro teor PDF url]
    H --> K[_persist: update_or_create idempotente]
    I --> K
    J --> K
    K --> L[Proposition + Event + Authors + Themes]
    L --> M[signal post_save]
    M --> N[classify_proposition.delay<br/>baixa+extrai PDF, loga]
    M --> O[match_and_notify.delay<br/>alertas por e-mail]
    K --> D
    D -->|fim| P[IngestionRun status=success<br/>contadores fetched/relevant/upserted/errors]
```

Erros por item são contados (`error_count`) e não interrompem a coleta; uma falha
geral (ex.: API fora) marca o `IngestionRun` como `failed` e a task tenta novamente
(`max_retries=2`, backoff 5 min).

### Saltos por casa

| Casa | Passo 1 (lista) | Passo 2 (detalhe) | Passo 3 (autores) | Passo 4 (inteiro teor) |
|------|-----------------|-------------------|-------------------|------------------------|
| **Câmara** | `/proposicoes` (paginado) | `/proposicoes/{id}` | `/proposicoes/{id}/autores` + `/deputados/{id}` | `urlInteiroTeor` (do detalhe) |
| **Senado** | `/materia/tramitando` | `/materia/{id}` | `/materia/autoria/{id}` | `/materia/textos/{id}` → PDF |

---

## URLs dos raspadores

### Câmara — `https://dadosabertos.camara.leg.br/api/v2`

| Método (client) | Endpoint | Uso |
|-----------------|----------|-----|
| `list_propositions(start, end)` | `GET /proposicoes?dataInicio={start}&dataFim={end}&ordem=ASC&ordenarPor=id&itens=100` | lista paginada da janela (segue `links.rel=next`) |
| `fetch_detail(id)` | `GET /proposicoes/{id}` | status, urls, `urlInteiroTeor`, ementa detalhada, keywords |
| `fetch_authors(id)` | `GET /proposicoes/{id}/autores` | autores (nome, tipo, uri) |
| `fetch_deputy(id)` | `GET /deputados/{id}` | `sexo`, `ultimoStatus.siglaPartido`, `siglaUf` |

### Senado — `https://legis.senado.leg.br/dadosabertos`

| Método (client) | Endpoint | Uso |
|-----------------|----------|-----|
| `list_materias(day)` | `GET /materia/tramitando?data=YYYYMMDD` | matérias em tramitação no dia |
| `fetch_detail(id)` | `GET /materia/{id}` | dados básicos, ementa, autor (texto livre) |
| `fetch_movements(id)` | `GET /materia/movimentacoes/{id}` | situação atual / último evento |
| `fetch_authors(id)` | `GET /materia/autoria/{id}` | autores com `CodigoParlamentar`, `SexoParlamentar`, `SiglaPartidoParlamentar`, `UfParlamentar` |
| `fetch_texts(id)` | `GET /materia/textos/{id}` | documentos (inteiro teor) |

### Documentos (PDF)

| Origem | Padrão de URL |
|--------|----------------|
| Câmara | `urlInteiroTeor` do detalhe (varia por proposição) |
| Senado | `http://legis.senado.leg.br/sdleg-getter/documento?dm={CodigoTexto}` |

> **Headers**: `User-Agent` próprio + `Accept: application/json`. Conexão keep-alive
> por client. Retry exponencial (tenacity) em erros de transporte/HTTP: 3 tentativas,
> espera 2→4→…→30s.
>
> ⚠️ O serviço `/materia/autoria` do Senado está marcado como **deprecated**
> (desativação anunciada 2026-02-01) mas segue ativo. Há fallback: se vier vazio,
> os autores são extraídos do texto livre do detalhe (mantém partido/UF, perde o
> sexo).

---

## Horários (agendamento)

Agendado pelo **Celery Beat** (`DatabaseScheduler`), definido em
[`config/settings/base.py`](../config/settings/base.py) → `CELERY_BEAT_SCHEDULE`.
Fuso: **`America/Sao_Paulo`** (`CELERY_TIMEZONE`).

| Task | Cron | Janela coletada |
|------|------|-----------------|
| `apps.ingestion.tasks.ingest_camara` | `06:00` (diário) | ontem → amanhã |
| `apps.ingestion.tasks.ingest_senado` | `06:10` (diário) | dia corrente (`/tramitando?data=hoje`) |

A janela ontem→amanhã (Câmara) absorve fusos/atrasos de publicação, igual ao bot
original. Coleta é **incremental** (não varre histórico) — backfill é processo
separado.

---

## Filtro de tema (`theme_assert`)

[`apps/ingestion/theme_assert.py`](../apps/ingestion/theme_assert.py). Roda sobre a
ementa **antes** de descer nos saltos caros, garantindo que só proposições
relevantes ao tema gênero/direitos das mulheres sejam processadas.

> **Editável no admin (Unfold)**: os termos ficam no modelo `RelevanceTerm`
> (`Coleta de dados → Termos de relevância`). A operação adiciona/remove/desativa
> termos **sem tocar no código**. Ao salvar/excluir, um signal limpa o cache e a
> próxima coleta já usa a lista nova. Os 96 termos originais (86 isolados + 10
> combinados) são carregados por migração de seed; enquanto a tabela estiver vazia,
> o filtro cai automaticamente nos defaults embutidos no módulo.

Usa duas expressões regulares (case-insensitive), montadas a partir dos termos:

1. **Termos relevantes por si só** (`_PATTERN_STANDALONE`, ~86 termos): ex.
   `ABORTO`, `FEMINICÍDIO`, `MULHER`, `GÊNERO`, `MARIA DA PENHA`, `ESTUPRO`,
   `VIOLÊNCIA DOMÉSTICA`, `LICENÇA MATERNIDADE`, `IDENTIDADE DE GÊNERO`, `CRECHE`…

2. **Termos relevantes só combinados com "mulher"** (`_PATTERN_COMBINED`):
   `COTAS`, `TRABALHO`, `RAÇA`, `PARTICIPAÇÃO POLÍTICA`, `RACIAL`, `POLÍTICA`,
   `RACISMO`, `RELIGIÃO`, `EDUCAÇÃO RELIGIOSA`, `DEUS` — só disparam se o texto
   também contém a palavra `mulher`.

```python
from apps.ingestion.theme_assert import assert_theme

assert_theme("Projeto sobre violência contra a mulher")
# {"row_relevant": True, "temas": ["violência contra a mulher"]}

assert_theme("Pavimentação de rodovia federal")
# {"row_relevant": False, "temas": []}
```

A função aceita múltiplos campos (ementa, ementa detalhada, keywords) e os
concatena. Na Câmara o filtro roda **duas vezes**: na lista (só ementa) e de novo
após o detalhe (ementa + ementa detalhada + keywords), para maior sinal.

### Temas no domínio

Os termos detectados (`temas`) viram `Theme` + `PropositionTheme` (com `rank`).
O `Theme.slug` é gerado por slugify do termo; reaproveita temas já existentes
(`get_or_create`). Exemplos de temas que aparecem no domínio:
`Violência Contra a Mulher`, `Lei Maria da Penha`, `Feminicídio`,
`Direitos Sexuais e Reprodutivos`, `Maternidade`, `Raça`, `Igualdade de Gênero`.

> A classificação temática/posicional por **ML** (modelos `azmina/*`) é separada e
> está como stub — ver `classify_proposition`. O `theme_assert` é o filtro
> determinístico por palavra-chave, não o classificador.

---

## Extração do inteiro teor (PDF)

[`apps/ingestion/fulltext.py`](../apps/ingestion/fulltext.py) — porta o
`textfrompdf` do bot, trocando `requests`+`PyPDF2` por `httpx`+`pypdf`.

```python
from apps.ingestion.fulltext import extract_pdf_text

texto = extract_pdf_text("http://legis.senado.leg.br/sdleg-getter/documento?dm=9904701")
# str com o texto extraído, ou None em qualquer falha
```

Comportamento:

- `url` vazio/None → `None`.
- Baixa o PDF (httpx, `User-Agent` de navegador, `follow_redirects`, timeout 60s).
- Erro HTTP/transporte → loga warning e retorna `None`.
- Extrai texto de todas as páginas via `pypdf` (`page.extract_text()`).
- PDF corrompido / sem texto extraível → `None` (não levanta exceção).

```mermaid
flowchart LR
    U[full_text_url] -->|vazio| N1[None]
    U -->|ok| D[httpx GET]
    D -->|erro HTTP| N2[None + warning]
    D -->|bytes| R[pypdf PdfReader]
    R -->|erro parse| N3[None + warning]
    R --> T[join page.extract_text]
    T -->|texto vazio| N4[None]
    T -->|texto| OUT[str]
```

### Seleção do PDF no Senado

O Senado expõe vários documentos por matéria. `pick_senado_full_text_url`
(em `mappers.py`) escolhe o **texto inicial** da proposição:

1. filtra só PDFs (`FormatoTexto == application/pdf`);
2. prioriza **não-derivados** (exclui relatório, parecer, emenda, voto, redação,
   substitutivo, errata);
3. entre os não-derivados, pega o **mais antigo** (apresentação).

O resultado vai para `Proposition.full_text_url`, equivalendo ao `urlInteiroTeor`
da Câmara. O `classify_proposition` então baixa/extrai esse PDF.

---

## Persistência e idempotência

`_persist` (em `tasks.py`) faz upsert idempotente numa transação:

- `Proposition.update_or_create(house, external_id)` — re-coletar não duplica.
- `raw_payload` (JSONField) guarda o payload cru → reprocessável sem re-raspar.
- `PropositionEvent` (último evento), `PropositionAuthor` (recriados a cada coleta,
  com partido/UF e sexo resolvidos), `PropositionTheme` (temas do `theme_assert`).
- Autores resolvidos por `resolve_author`: existente via `ParliamentarianTerm`
  (por `external_id`), institucional (`InstitutionalAuthor`) ou parlamentar mínimo
  criado pelo nome. Sexo grava em `Parliamentarian.gender` (com backfill quando vazio).

Cada execução registra um `IngestionRun` (casa, janela, status, contadores
`fetched/relevant/upserted/errors`) — visível no admin (read-only).

---

## Como rodar

```bash
# infra
docker compose up -d postgres redis
uv run python manage.py migrate

# worker + agendador
uv run celery -A config worker -l info
uv run celery -A config beat -l info

# disparo manual
uv run python manage.py shell -c "from apps.ingestion.tasks import ingest_senado; ingest_senado.delay()"
```

### Testes

```bash
uv run pytest apps/ingestion/tests/ --no-migrations \
  --cov=apps/ingestion --cov-report=term-missing --cov-fail-under=95
```

> `--no-migrations` é necessário: as apps de domínio não têm migrations commitadas;
> o pytest-django cria o schema direto dos models. Fixtures reais (capturadas das
> APIs) ficam em `apps/ingestion/tests/fixtures/`.
