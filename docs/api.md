# API HTTP

API Django Ninja montada em `/api/v1/` (`config/api.py`, `config/urls.py`).

- Documentação interativa: `/api/v1/docs`; schema: `/api/v1/openapi.json`.
- **Sem autenticação**: todos os endpoints são públicos. O admin usa sessão Django.
- **Escopo público**: proposições, atividade e estatísticas consideram apenas
  `is_approved=True` e tipos de `PUBLIC_LEGISLATIVE_TYPES` (PEC, PL, PLP, PLV,
  PDC, PRC, PLS, PLN, PRS, PDS).
- **Paginação** `limit`/`offset` (Ninja `LimitOffsetPagination`, padrão 100),
  resposta `{"items": [...], "count": N}`, quando indicado como L/O.
- **CORS** apenas em `/api/*`, para `CORS_ALLOWED_ORIGINS`.
- **Throttling** apenas em `POST /subscriptions/` (padrão 10/h por IP; 429).
- **Cache**: endpoints `/activity*` usam chaves `activity:*` por 5 minutos;
  os demais não têm cache. A invalidação está descrita na
  [ADR-004](decisions/004-estrutura-do-banco.md#leitura-do-explorer).

## Rotas fora do Ninja

| Rota | Descrição |
| --- | --- |
| `GET /health/` | Liveness: `{"status": "ok"}`, sem cache |
| `GET /health/ready/` | Readiness: `SELECT 1` no banco e set/get no cache; 200 `ready` ou 503 `unavailable` com `checks` |
| `GET /api/v1/assets/emails/<nome>` | Apenas `daily-header.png` e `header.png`; `Cache-Control` de um ano, `immutable` |
| `{ADMIN_URL}` | Django admin (padrão `/admin/`) |

`HealthCheckHostMiddleware` reescreve o `Host` das rotas de health para
`localhost`, permitindo probes com o ID do container como host.

## Legislaturas e parlamentares

| Método e caminho | Parâmetros | Resposta |
| --- | --- | --- |
| `GET /legislatures/legislatures` | — | `[{number, start_date, end_date}]`, mais recente primeiro |
| `GET /legislatures/parties` | — (L/O) | `{id, acronym, name, ideology}` |
| `GET /legislatures/parliamentarians` | `house`, `state`, `party`, `gender`, `current` (bool), `rank=unfavorable\|unfavorable_rate`, `min_propositions`, `min_unfavorable_rate` (L/O) | Parlamentar com `terms[]` e contagens `public_`, `favorable_`, `unfavorable_propositions_count` |
| `GET /legislatures/parliamentarians/{id}` | — | Detalhe com contagens |

As contagens usam a avaliação exibida: anotação humana ou, na falta dela, a
QuitérIA.

## Atividade legislativa

| Método e caminho | Parâmetros | Resposta |
| --- | --- | --- |
| `GET /activity/` | `limit` (1–5000, padrão 5000), `include_events` (padrão `true`, até 5 eventos) | Lista de proposições com avaliação, celeridade e eventos |
| `GET /activity/fast-unfavorable` | — | Desfavoráveis "Rápida" ou "Tá voando" com movimentação em 90 dias, mais movimentadas primeiro |
| `GET /activity/slow-favorable` | — | Até 50 favoráveis "Lenta" ou "Travada", mais tempo paradas primeiro |
| `GET /activity/enacted-projects` | `limit` (1–50) | Avaliadas que viraram norma (Câmara status 1140; Senado 64/92), com `assessment_label` e `enactment` |
| `GET /activity/by-number` | `house`, `number_label` (obrigatórios) | Uma proposição com todos os eventos |
| `GET /activity/{id}` | — | Uma proposição com todos os eventos |
| `GET /activity/explorer` | ver abaixo | `{items, total, page, page_count, options, summary, dashboard}` |
| `GET /activity/explorer/export` | mesmos filtros | CSV `atividade-legislativa.csv` sem paginação |

### Filtros do explorer

Definidos em `ExplorerQuery` (`apps/propositions/explorer.py`):

| Parâmetro | Valores |
| --- | --- |
| `search` | Texto livre |
| `house` | `camara`, `senado` |
| `year`, `year_start`, `year_end` | Inteiros; `year_start ≤ year_end` |
| `assessment` | `favorable`, `unfavorable`, `unrated` |
| `movements` | `with`, `without` |
| `gender` | Gênero da autoria |
| `comments` | `yes`, `no` |
| `party`, `category`, `celerity`, `state`, `religion`, `evaluator` | Multivalor (repita o parâmetro; combinação OU). `religion=__unknown__` = "Não informada" |
| `page`, `page_size` | `page ≥ 1`; `page_size` 1–100, padrão 10 |
| `sort`, `direction` | `number`, `author`, `summary`, `assessment`, `evaluator`, `progress`, `category`, `updated` |
| `party_sort`, `author_sort` | `unfavorable`, `favorable`, `total` |
| `author_minimum` | Mínimo de proposições por autoria no painel (padrão 5) |

Os filtros e o `dashboard` (gênero, casa, partido, autoria, UF com as 27
unidades, categoria e situação) são calculados no servidor sobre todo o
conjunto; a paginação não altera os totais. Em proposições com coautoria,
autores diferentes podem satisfazer critérios diferentes.

O CSV usa `;`, BOM UTF-8, todos os campos entre aspas e 11 colunas em português.

## Proposições

| Método e caminho | Parâmetros | Resposta |
| --- | --- | --- |
| `GET /propositions/` | `house`, `year`, `theme` (slug), `active`, `q`, `sort=newest\|oldest` (L/O) | Proposição sem `raw_payload` |
| `GET /propositions/{id}` | — | Mesmo schema |

`q` busca em número, ementa, palavras-chave e autorias, sem diferenciar acentos.

## Dataset

| Método e caminho | Parâmetros | Resposta |
| --- | --- | --- |
| `GET /dataset/` | `house`, `year`, `include_unlabeled` (padrão `false`) (L/O) | Uma linha por anotação × autoria (19 campos) |
| `GET /dataset/download` | `format=csv\|jsonl\|parquet` e os mesmos filtros | Arquivo completo; CSV/JSONL em streaming, Parquet em memória; formato inválido → 400 |

## Estatísticas

| Método e caminho | Parâmetros | Resposta |
| --- | --- | --- |
| `GET /stats/propositions/legislatures` | `last` (padrão 2; 0 = todas) | `{legislatures: [{number, from, to, label, unfavorable}]}` |
| `GET /stats/propositions/categories` | — | `{categories: [{value, label, unfavorable}]}` |
| `GET /stats/propositions/genders` | — | `{women: {favorable, unfavorable}, men: {...}}` em proporções |
| `GET /stats/propositions/parties` | `stance=unfavorable\|favorable`, `limit` (padrão 5) | `{parties: [{label, favorable, unfavorable}]}` |
| `GET /stats/propositions/states` | idem | `{states: [{label, favorable, unfavorable, total, *_percentage}]}` |

## Taxonomia, comissões e normas

| Método e caminho | Parâmetros | Resposta |
| --- | --- | --- |
| `GET /taxonomy/categories` | — | `[{value, label}]` das 10 Categorias 2026 |
| `GET /taxonomy/themes` | — | `{id, slug, name}` |
| `GET /taxonomy/tags` | — | `{id, slug, name, description}` |
| `GET /committees/` | `house`, `active` (L/O) | `{id, house, acronym, name, kind, is_active}` |
| `GET /norms/` | `type`, `q` (em `official_name`) (L/O) | Campos de `LegalNorm` |

## CMS

| Método e caminho | Parâmetros | Resposta |
| --- | --- | --- |
| `GET /cms/alerts` | — | Topo de `/alertas`: `{title, subtitle, hero_image: {url, width, height}}`, com `?v=` na URL da imagem; `Cache-Control: no-store` |
| `GET /cms/reports` | — | Topo de `/reportagens`, mesmo formato |
| `GET /cms/activity` | — | Topo de `/atividade-legislativa`, mesmo formato |
| `GET /cms/feminist-ai` | — | Conteúdo de `/ia-feminista`: `content` (campos de texto e links), `images` (`hero`, `flow_desktop`, `flow_mobile`), `categories`, `limitations`, `evaluation_metrics`, `evaluation_partitions`, `thematic_metrics`, `thematic_partitions` e `open_links`; `Cache-Control: no-store` |
| `GET /cms/about` | — | Conteúdo de `/sobre`: `content` (SEO, textos e links), `hero_image`, `timeline`, `challenges` e `partners`; `Cache-Control: no-store` |
| `GET /cms/home` | — | Conteúdo editorial da home: `hero_image` e `content` (títulos, textos, imagens, post-its, legendas e CTAs); `Cache-Control: no-store` |
| `GET /cms/footer-alerts` | — | Bloco global de alertas no rodapé: `{title, text, cta_text, cta_url}`; `Cache-Control: no-store` |

Lido pelo build do site ([ADR-006](decisions/006-cms-do-site.md)).
As listas de `/cms/feminist-ai` já vêm na ordem editorial. `trend` nas métricas
é `up`, `down` ou `neutral`; os valores e percentuais são textos prontos para
exibição. As três imagens incluem `{url, width, height}` e `?v=` na URL. Os
campos de `content` têm os nomes do model `FeministAIPage`; parágrafos com link
usam `*_before_link`, `*_link_text`, `*_link_url` e `*_after_link`.
Em `/cms/about`, as listas vêm em ordem editorial. Cada marco traz período,
ano, descrição, link opcional e etiqueta. Uma organização traz nome,
`asset_key` para o logo original do site e `logo_url` quando a equipe enviou
outro logo; o site usa `logo_url` quando presente. O endpoint inclui `?v=` nas
URLs das imagens enviadas para atualizar o cache.
Em `/cms/home`, dados de gráficos, cards de notícias, tabelas e mapas seguem
nas APIs existentes. O percentual do post-it feminino continua vindo da API
de estatísticas. A ilustração do topo inclui `{url, width, height}` e `?v=`; as
imagens de Explore e QuitérIA usam Markdown padrão dentro de `content`.

## Inscrições em alertas

| Método e caminho | Resposta |
| --- | --- |
| `POST /subscriptions/` | 201 com a lista de inscrições criadas; 422 em validação; 429 no limite |
| `GET /subscriptions/confirm/{token}` | 302 para `{PUBLIC_SITE_URL}/?subscription=confirmado` ou `invalido` |
| `GET /subscriptions/unsubscribe/{token}` | 302 para `{PUBLIC_SITE_URL}/alertas/cancelado?status=ok` ou `invalido` |

As rotas de token não aparecem no OpenAPI. Corpo da criação, critérios e efeitos
estão em [alertas.md](alertas.md).
