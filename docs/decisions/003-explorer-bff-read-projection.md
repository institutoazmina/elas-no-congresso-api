# ADR-003: Projeção de leitura específica para o BFF do explorer

## Status

Aceita — implementação local validada; publicação acompanha o deploy da alteração.

## Contexto

O frontend precisa de itens paginados, opções globais e dashboards do resultado
completo. O explorer reutilizava o queryset/serializer de detalhes: carregava
textos integrais, JSONs oficiais, perfis completos e todo o histórico de eventos.
Mesmo com `event_limit=0`, os eventos eram materializados e ordenados em Python.

Três misses HTTP em produção levaram 39,33 s, 50,92 s e 12,17 s. O estágio de
carregamento consumiu 37,57 s, 49,21 s e 11,32 s. A quantidade de consultas não
era N+1: foram dez, mas a materialização chegava a aproximadamente 60 mil objetos.
O container de 512 MiB registrou pressão de memória e uso de swap.

## Decisão

Manter um caminho de leitura próprio em `explorer_source.py`, usado somente pelo
explorer e seu CSV, com cinco consultas de projeções explícitas:

1. Proposições públicas e três campos da análise, por LEFT JOIN.
2. Agregados de eventos contáveis (`MAX(event_at)` e `COUNT` na janela de 90 dias).
3. Campos da anotação humana e nome da organização.
4. Campos das autorias, identificação/foto/gênero/religião e partido.
5. Nomes de temas, preservando o contrato HTTP existente.

As consultas retornam dicionários/tuplas, sem modelos Django. Relações com
múltiplas linhas são consultadas separadamente para impedir multiplicação de
linhas e contagens. Eventos não atravessam a conexão como históricos completos.
Os dados de anotação e autoria têm desempate explícito por PK; o caminho antigo
não definia ORDER BY nessas relações. Isso estabiliza a seleção/primeira autoria.

Compartilhar apenas a regra de celeridade (`celerity_from_summary`) com detalhes.
Preservar a janela por data UTC dos eventos, usando a data local para “hoje”,
inclusive o comportamento atual com datas futuras. Não mudar o contrato da UI
ou o comportamento das outras rotas nesta alteração.

O cache passa a `activity:explorer:source:v3`. Um único snapshot guarda itens,
opções e texto de busca normalizado; a mesma invalidação expira o conjunto.
A data local de construção impede reutilizar a celeridade do dia anterior.
Continuam o TTL de cinco minutos e a invalidação `activity:*` existente.

## Alternativas e limites

- Aumentar TTL: reduz alguns misses, mas não reduz custo nem memória da reconstrução.
- Adicionar índices antes de mudar as consultas: não elimina transferência de
  colunas grandes ou criação dos modelos; avaliar planos das consultas novas.
- Mover todos os filtros e dashboards para SQL nesta entrega: exigiria reproduzir
  normalização, ordenação natural e regras especiais de coautoria PL, ampliando
  o risco. O snapshot estreito resolve o gargalo medido mantendo essas regras.
- Alterar payload para remover campos sem consumo: possível depois; não é
  necessário para eliminar a materialização pesada. Temas continuam em projeção
  estreita para preservar o contrato.

Ainda há processamento linear sobre a coleção pública, reconstruções concorrentes
não têm trava e as invalidações globais continuam amplas. Esses problemas não
foram declarados resolvidos. Medir novamente a rota pública após o deploy antes
de escolher uma segunda intervenção.

## Validação

86 testes no PostgreSQL do Docker: filtros, dashboards, CSV, cache, regras de
celeridade, equivalência com serializer anterior, cinco queries e proibição
explícita de `Model.from_db` na nova leitura. O teste de SQL rejeita colunas
pesadas (`full_text`, `raw_payload`, scores e bio).

Três execuções da implementação nova no banco de produção, em processo isolado,
transação READ ONLY e bypass sem escrita no cache público:

| Execução | BFF + validação/JSON | Carregamento | SQL | Pico RSS do processo |
| --- | ---: | ---: | ---: | ---: |
| 1 | 703 ms | 440 ms | 267 ms | 107,2 MiB |
| 2 | 669 ms | 405 ms | 181 ms | 108,1 MiB |
| 3 | 677 ms | 418 ms | 232 ms | 108,6 MiB |

Coleção: 3.381 proposições, 5.603 autorias; filtro Câmara/2023–2026 com 2.038
resultados. Dez itens comparados contra o serializer antigo em produção, sem
diferenças. Dados em `docs/performance/explorer-bff-2026-10-07.jsonl`.

O probe não inclui rede/proxy, middleware HTTP ou cache Redis; a conexão foi
aberta antes da medição, os buffers do PostgreSQL não foram esvaziados e não
houve teste de carga. Não comparar seus totais como latência HTTP ou p95.
`source_load` inclui os subestágios de consultas e serialização: não somá-los.
