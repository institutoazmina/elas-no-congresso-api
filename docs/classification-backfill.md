# Cobertura de avaliações QuitérIA

O workflow **Quiteria evaluation backfill** preenche lacunas de categoria e
favorabilidade no inventário monitorado, inclusive proposições não aprovadas e
encerradas. Uma anotação humana (inclusive parcial) ou revisão legada em
`expert_id`/`expert_opinion` exclui a proposição. Uma análise com categoria válida
e favorabilidade 0/1 também a exclui; resultados de IA parciais entram no backfill.
Avaliações humanas e a aprovação pública não são alteradas.

## Operação

Em Actions → Quiteria evaluation backfill, selecionar `main`:

- `preview` ou `status`: consulta somente leitura, com total, lacunas, candidatos
  prontos para fila e estados dos pedidos das proposições ainda sem avaliação.
- `queue`: prepara os pedidos ausentes. `limit=0` inclui todos; um limite positivo
  permite lotes menores. A conclusão do workflow significa pedidos persistidos e
  enfileirados, não que a inferência já terminou.
- `retry`: também reabre pedidos falhos da versão/configuração atual, zerando as
  tentativas. Também retoma execuções abandonadas há pelo menos 90 minutos;
  ainda exclui proposições já avaliadas e tarefas em execução recente.

```sh
gh workflow run classification-backfill.yml --ref main -f mode=preview
gh workflow run classification-backfill.yml --ref main -f mode=queue -f limit=0
gh workflow run classification-backfill.yml --ref main -f mode=status
```

O comando equivalente é `python manage.py classification_backfill --mode queue`.
Ele usa o container web e o host/SSH do deploy Kamal; não descobre contas AWS.
A inferência executa no worker ML já existente. Não gera alertas retroativos aos
assinantes. Sem QuitérIA habilitada, preparação falha explicitamente.

## Eficiência e proteção das avaliações

O backfill usa a versão de texto substantivo selecionada, incluindo substitutivo.
Sem versão registrada, cria uma versão do inteiro teor já armazenado ou, como
fallback, da ementa. Não consulta fontes oficiais nem baixa PDFs/OCR. A ingestão
diária continua responsável por descobrir novos textos e suas classificações.

Pedidos são únicos por proposição, hash de texto e configuração. Repetir `queue`
não duplica pedidos pendentes nem reexecuta resultados já disponíveis. Um resultado
em cache pode restaurar uma análise ausente. A avaliação é verificada antes e
depois da inferência: uma revisão humana feita durante a espera impede aplicação
do resultado. A troca de texto/configuração também invalida o pedido antigo.

Às **06:45 em America/Sao_Paulo**, uma varredura diária prepara até **600** lacunas
ainda sem pedido ativo, configuradas pela repository variable
`CLASSIFICATION_BACKFILL_DAILY_LIMIT` (requer redeploy após alteração).
A recuperação existente a cada 15 minutos retoma pedidos interrompidos ou falhos,
com até três tentativas. Falhas esgotadas aparecem no status e exigem `retry`;
nunca são registradas como avaliação concluída. Isso complementa a decisão de não
classificar todo o histórico durante a baseline da ingestão ([ADR-002](decisions/002-daily-ingestion-content-versions.md)).
