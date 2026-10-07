# Explorer: diff dos dados necessários

Revisão em 2026-10-07 do frontend `../elas-no-congresso/src` e da API.
Proposta para revisão; nenhuma alteração funcional aplicada.

## Evidência de consumo

- `src/scripts/activity-legislative.ts:170`: adapta os itens recebidos.
- `:241`: apresenta somente a primeira autoria e a quantidade das demais.
- `:351`: consome todos os sete dashboards devolvidos pela API.
- `:437`: tabela; `:479`: cards; `:507`: resumo; `:531`: paginação.
- `:163`: opções globais; `:194`: parâmetros enviados; `:728`: export CSV.
- `:845`: busca o explorer. O tipo compartilhado em `src/lib/activity-api.ts`
  é mais amplo que o consumo efetivo desta página.
- `src/pages/atividade-legislativa/proposicao/[slug].astro`: detalhes consomem
  temas, eventos e celeridade completa, inclusive via `/activity/by-number`.
  Esses consumidores não recebem os itens do explorer.

## Diff principal: leitura do banco

O ganho principal está antes do JSON. O queryset compartilhado traz todas as
colunas dos modelos e suas relações. `event_limit=0` esvazia a saída, mas não
impede carregar nem ordenar todos os eventos.

```diff
- Proposition: todas as colunas, inclusive full_text e raw_payload
+ id, house, type_code, number_label, ementa, presented_at, current_status
+ is_approved e type_code continuam restringindo o universo público

- PropositionAnalysis: modelo completo, scores/JSON, resumos e metadados
+ proposition_id, theme_category, analysis_status, classification

- PropositionEvent: todos os registros como modelos e todos os campos
- ordenar histórico inteiro em Python
+ por proposition_id: MAX(event_at) dos eventos is_countable=True
+ por proposition_id: COUNT dos eventos is_countable=True na janela de 90 dias
+ calcular label/days_without_movement a partir desses agregados e presented_at

- PropositionTheme + Theme: prefetch e lista de nomes para toda a coleção
+ nenhuma leitura de temas no explorer; category/category_label são suficientes

- PropositionAnnotation: modelo completo e objeto completo da organização
+ anotação escolhida: is_favorable, category, comments, organization.name
+ IDs/FKs necessários à associação e à escolha consistente

- Parliamentarian: perfil completo (bio, profissão, nascimento etc.)
+ id, social_name, full_name, photo_url, gender, religion

- InstitutionalAuthor: modelo completo
+ id, name

- Party: modelo completo
+ id, acronym

- PropositionAuthor: modelos relacionados completos
+ proposition_id, parliamentarian_id, institutional_author_id,
+ party_id, state_at_authorship, campos necessários à ordem das autorias
```

Omitir `tramitation_url`, temas e relevância da leitura pressupõe um serializer
específico do explorer e a revisão do seu contrato. Se a primeira entrega
preservar exatamente o contrato atual, mantenha esses campos com projeções
estreitas, e ainda assim elimine os objetos de eventos em favor dos agregados.
Não preencher campos antigos com dados fictícios só para satisfazer o schema.

Evitar um único JOIN de eventos × autores × anotações: multiplica linhas e
pode inflar contagens. Agregar eventos separadamente por proposição. Usar
projeções explícitas (`values` ou `only` com FKs e serializers adequados) sem
provocar consultas adicionais ao acessar campos deferred.

## O que deve continuar no servidor

| Dados | Motivo |
| --- | --- |
| `type_code` | Regra especial de coautoria de PL e escopo legislativo |
| `current_status` | Dashboard de situação e coluna Situação do CSV |
| `authors.id` e identificação institucional | Deduplicação e chave dos dashboards; religião desconhecida |
| `authors.gender`, `authors.religion`, `authors.state`, `authors.party` | Filtros, opções e painéis por autoria |
| Todas as autorias | Busca, recortes, contagens, dashboard e CSV |
| `assessment_comments` completo | Exportação CSV; filtros de presença de comentário |
| `ementa`, `number_label`, avaliador e nomes/partido/UF | Busca e ordenação |
| `presented_at` | Ano dos filtros, data exibida, ordenação updated e fallback da celeridade |
| Último evento contável | Determina inatividade e rótulo, mesmo não exibido na tabela |
| Contagem contável em 90 dias | Filtro movements, ordenação progress, rótulo e tabela |

Os dados usados para filtrar/agregar não precisam ser devolvidos em cada item
HTTP. Contudo, não podem simplesmente ser excluídos do modelo de leitura.

## Diff opcional: contrato HTTP específico do explorer

Requer atualizar tipos/adaptador do frontend junto com o schema da API.
É uma redução de payload; não substitui a redução de leitura acima.

```diff
 items[]:
   id, house, number_label, ementa, presented_at
   category, category_label, is_favorable, assessment_organization
-  current_status
-  tramitation_url
-  themes
-  relevance
-  events                       # hoje já retorna []
-  assessment_comments: string | null
+  has_comments: boolean
   celerity:
     label, movements_last_90_days
-    days_without_movement
-    last_event_at
   authors[]:
     id, name, party, state, photo_url
-    gender
-    religion
-    role
```

`tramitation_url` é copiado para `Proposal.link`, mas o render usa
`propositionRoute(item.numero)`; `link` não é lido. `id` é copiado para `i`
e o ID de autoria para `numero`, também sem uso no render atual. Recomenda-se
preservar os IDs como identidade estável, pois removê-los traz pouco ganho.

A presença de comentário controla apenas o ícone/link e o texto do card. Seu
conteúdo fica no detalhe e no CSV. Atenção: a UI atual usa truthiness do texto,
enquanto o filtro backend usa `strip()`. A troca por booleano precisa definir
e testar explicitamente a regra para comentários com apenas espaços.

Outra redução possível, independente, seria substituir `authors[]` por
`primary_author` e `author_count` nos itens. A UI apresenta só a primeira autoria
mais `+ N autorias`; o servidor e o CSV continuam precisando de todas. Essa
mudança também exige adaptar o frontend e preservar a ordem atual.

## Blocos que o frontend realmente usa por inteiro

Manter `total`, `page`, `page_count` e todos os campos de `summary`.
Manter opções globais `year`, `party`, `state`, `category`, `evaluator`,
`celerity`, `religion`, independentes da página e dos filtros selecionados.
Manter os sete dashboards: `gender`, `house`, `party`, `author`, `state`,
`category`, `status`, calculados sobre o resultado filtrado completo.

Os gráficos usam label, contagens e larguras; autores usam também key, photo e
meta; o mapa usa key, contagens, favorable_percent e color. Não basta paginar o
queryset e calcular esses blocos com os dez itens retornados.

`options` pode ter cache global próprio. Resumo/dashboard dependem do conjunto
filtrado e dos controles dos painéis, mas não da página. Mudar apenas `page`,
`page_size`, `sort` ou `direction` não precisa refazer suas agregações. Mudanças
em `party_sort`, `author_sort` e `author_minimum` precisam refletir nos painéis.

## Semânticas a preservar na implementação

- Anotação humana tem precedência: desfavorável, depois favorável, depois a
  primeira disponível. QuitérIA só fornece avaliação com status SUCCEEDED e
  classificação 0/1; categoria atualmente pode vir da análise mesmo sem sucesso.
- A celeridade considera só eventos contáveis, janela inclusiva desde hoje−90
  dias e fallback em presented_at. Preservar conversão de data/fuso do código
  atual: `event_at.date()` não equivale automaticamente ao `__date` do Django.
  O código atual também não impõe limite superior para eventos futuros.
- Em PL, autores diferentes podem satisfazer critérios diferentes de gênero,
  UF e religião. Nos painéis de autoria entra quem contribui para esse recorte.
  Em outros tipos, os critérios precisam coincidir numa mesma autoria.
  A documentação do frontend ainda descreve só a segunda regra: o código e os
  testes atuais da API são a referência a preservar.
- Preservar deduplicação por pessoa nos painéis, contagem de proposições,
  autores institucionais, não avaliadas e author_minimum (inclui não avaliadas).
- CSV ignora paginação e mantém comentários completos, todas as autorias e status.
- Detalhes de proposição e outras rotas continuam com histórico/temas completos.

## Ordem proposta

1. Criar leitura e serializer próprios para explorer/export, sem alterar o
   `_queryset()` compartilhado com as telas de detalhe e demais endpoints.
2. Agregar eventos no banco e limitar colunas de proposição, análise e relações.
   Comparar saída com a atual para filtros, regras editoriais, dashboards e CSV.
3. Medir novamente três misses reais e memória. Só então avaliar índices com
   os planos das novas consultas; já existe `(proposition_id, event_at DESC)`.
4. Separar cache de opções e agregados por filtros, investigar invalidações e
   proteger reconstruções concorrentes. Celeridade muda com o dia mesmo sem escrita.
5. Enxugar o contrato HTTP se o ganho de payload justificar a mudança coordenada.
