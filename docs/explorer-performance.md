# Diagnóstico de performance do explorer em produção

O explorer usa uma projeção própria de leitura, com colunas explícitas e
agregados de eventos, sem materializar históricos como modelos Django.
`activity:explorer:source:v3` guarda a coleção pública, opções e busca normalizada
por 300 segundos; snapshots de outro dia local são reconstruídos para atualizar
celeridade. Alterações passam por `invalidate_activity_cache`, que remove
`activity:*`. Não há trava de reconstrução: misses simultâneos podem repetir trabalho.

A motivação, limites e medições estão na
[ADR-003](decisions/003-explorer-bff-read-projection.md).

## Executar via SSH

Depois de disponibilizar esta versão na produção, entre no host por SSH e
identifique o container web (os comandos abaixo rodam **no host de produção**).
A imagem distroless não tem shell; use Python diretamente com `docker exec`.

```sh
docker ps --format '{{.Names}}\t{{.Image}}'
API_CONTAINER='nome-do-container-web'
docker exec "$API_CONTAINER" python manage.py profile_activity_explorer --runs 3 > explorer-cache.jsonl
```

O modo padrão usa o cache normalmente: se ele estiver ausente, reconstrói e
preenche, como uma visita real. Cada linha de stdout contém uma medição JSON;
logs vão para stderr. Não trate a primeira execução automaticamente como miss:
confira `source_cache`. Para usar os mesmos filtros da requisição lenta:

```sh
docker exec "$API_CONTAINER" python manage.py profile_activity_explorer \
  --query 'year_start=2023&house=camara&page=1&page_size=10' --runs 3
```

Compare com uma reconstrução explícita. Execute uma vez inicialmente, pois ela
carrega a coleção inteira e compete por CPU, memória e banco com o tráfego real.
Não limpa, lê ou sobrescreve a chave compartilhada:

```sh
docker exec "$API_CONTAINER" python manage.py profile_activity_explorer --bypass-cache
```

Para atribuir custo a funções Python, gere um perfil separado; seus tempos têm
o overhead do profiler e não devem ser usados como baseline:

```sh
docker exec "$API_CONTAINER" python manage.py profile_activity_explorer \
  --bypass-cache --profile /tmp/explorer.prof
docker cp "$API_CONTAINER":/tmp/explorer.prof ./explorer.prof
python -c 'import pstats; pstats.Stats("explorer.prof").strip_dirs().sort_stats("cumulative").print_stats(35)'
```

O comando usa o pipeline Django, incluindo validação Ninja e renderização JSON.
É um processo separado: não mede fila de entrada do servidor ASGI, rede, proxy,
Cloudflare ou concorrência real. Sua primeira execução também pode abrir uma
conexão ao banco. `--bypass-cache` não esfria buffers do PostgreSQL/OS.

## Observar visitantes reais

Defina `ACTIVITY_EXPLORER_TRACE_SAMPLE_RATE=1` no ambiente do deploy Kamal para
uma janela curta de diagnóstico (ou `0.1` para uma amostra de 10%) e recrie o web
com essa configuração. A configuração padrão é `0`, desativada. Mudar a variável
apenas em uma sessão SSH não altera o processo web existente. O comando acima
força sua própria medição e independe desta variável.

```sh
docker logs --since 15m "$API_CONTAINER" 2>&1 \
  | grep '"event": "activity_explorer_performance"'
```

O header `X-Explorer-Trace-ID` correlaciona a resposta amostrada com o log. Cada
registro tem PID, status HTTP, bytes, contagens da coleção, nomes dos filtros
ativos (sem valores), hit/miss e durações. Não registra SQL bruto, parâmetros,
termos de busca, cookies nem dados de usuários. Os grupos SQL são limitados a
20 fingerprints mais um grupo overflow, evitando crescimento ilimitado em N+1.
A instrumentação SQL funciona com `DEBUG=False`. Desative a amostragem ao final.

## Interpretar os tempos

| Campo | O que mede |
| --- | --- |
| `total_ms` | Pipeline Django após entrada no middleware, incluindo renderização da resposta |
| `thread_cpu_ms` | CPU da thread síncrona; compare com tempo total para distinguir CPU de espera |
| `cache_get` | Redis + transferência + desserialização do valor |
| `source_load` | Total das cinco projeções e montagem dos itens; inclui os subestágios abaixo |
| `source_propositions`, `source_events`, `source_assessments`, `source_authors`, `source_themes` | Consulta, fetch e associação da respectiva projeção |
| `source_serialize` | Celeridade a partir dos agregados e montagem dos itens |
| `source_prepare` | Opções e normalização da busca preparadas para o snapshot |
| `cache_set` | Serialização do valor + escrita no Redis |
| `filter`, `sort`, `options`, `dashboard` | Processamento Python da coleção |
| `sql_execute_ms` | Soma dos tempos do cursor execute; está **dentro** dos estágios, não some novamente |
| `sql_groups` | Quantidade/tempo por template SQL (hash) e estágio; evidencia N+1 |

`sql_execute_ms` não isola tempo de execução no servidor PostgreSQL: pode incluir
rede/buffering e não inclui necessariamente todo o fetch, conexão ou hidratação.
Use o perfil para detalhar essas diferenças; se SQL dominar, prossiga com planos
de execução das consultas identificadas no código. O residual de `total_ms`
menos os estágios de primeiro nível (sem somar os subestágios de `source_load`) inclui middleware, validação/renderização, contagem de resumo,
liberação de objetos e overhead; não atribua todo o residual à serialização.
Para separar Redis/rede de unpickle, consulte as funções correspondentes no perfil.
O profiler não coleta variáveis locais.

Hipóteses a confrontar com os dados:

1. Reconstrução domina: misses/bypass têm `source_load` ou `source_serialize`
   altos, enquanto hits caem bastante. Priorizar projeção menor, agregados de
   eventos e reconstrução fora da requisição.
2. Hits continuam caros: `cache_get`, filtros ou dashboard dominam. Avaliar
   tamanho da coleção, opções pré-calculadas e cache de resultados por filtros.
3. Invalidação/expiração provoca misses repetidos: observar proporção de miss
   ao longo do tempo e correlacionar com ingestão/edições e janela de 300s.
   Logs de requisições sozinhos não identificam qual escritor invalidou a chave.
4. Custo está fora do pipeline: cliente vê 15–32s mas `total_ms` fica baixo.
   Investigar fila ASGI, saturação do host e proxy, correlacionando o trace ID.

Não estime p95 com três execuções. Reúna uma janela representativa de tráfego,
separe hit/miss, filtros, volume e concorrência antes de escolher TTL, locks,
pré-aquecimento ou uma projeção persistente.
