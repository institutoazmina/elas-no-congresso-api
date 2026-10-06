# ADR-002: Ingestão diária com cobertura persistida e IA por versão de texto

## Status

Aceito — 2026-10-06. Substitui o refresh semanal de históricos do ADR-001.

## Contexto

O disparo manual 37495777475 percorreu 3.754 proposições e fez pelo menos 6.698
leituras da Câmara antes de falhar por autenticação no Substack. A rotina diária
também classificava proposições em qualquer atualização, mesmo quando só mudava
o status. A equipe quer um banco fresco e rascunhos rápidos, com revisão humana.

## Decisão

Concentrar descoberta e atualização de atividade na ingestão diária. Persistir
checkpoints e itens por execução; avançar cobertura apenas após todos os itens
terminarem. Usar feed de processos do Senado incluindo encerrados, preservar IDs
legados e resolver vínculos ausentes. Atualizar proposições conhecidas antes do
filtro de relevância aplicado às novas. Fazer baseline do inventário uma vez e
reconciliação periódica limitada, incluindo correções históricas e documentos.

Separar documento, versão imutável de texto e pedido de classificação. Guardar
URL/revisão/data, validadores HTTP e hashes de bytes/texto. Classificação usa
chave única por proposição, texto e configuração do modelo; resultados atrasados
não podem substituir uma versão mais recente. Metadados e status não criam novos
pedidos. Textos históricos da primeira baseline não iniciam backfill de IA.

A política confirmada pela equipe inclui substitutivos e redações integrais;
exclui pareceres, documentos processuais e emendas parciais sem texto integral
identificável. Guardar o texto original separadamente do substitutivo selecionado.
Preservar análises humanas, aprovação, regras de alertas e snapshots congelados.

Geração normal da newsletter consulta apenas PostgreSQL e cobertura das fontes.
Cobertura incompleta preserva exportação e bloqueia entrega automática; uma
exceção manual explícita mantém o aviso. O workflow verifica acesso ao Substack
antes de qualquer preparação. Manter refresh integral apenas como recuperação.

## Alternativas

- Reclassificar por hash do input completo: alterações de partido/autoria também
  disparariam IA, contrariando a política de texto substantivo.
- Atualizar todas as proposições no disparo semanal: repete trabalho diário,
  demora proporcionalmente ao inventário e mistura coleta com autenticação.
- Confiar somente na data de atualização do registro: ela não comprova cobertura
  de fontes nem distingue atividade legislativa de manutenção interna.

## Consequências

Há novos estados persistidos para observar e recuperar. A primeira baseline
continua tendo custo de leitura do inventário. Correções silenciosas sem sinal
no feed são detectadas no ciclo de reconciliação, não necessariamente no mesmo
dia. O feed do Senado limita recuperação incremental a 30 dias; catch-up explícito
reinicia cobertura recente sem alegar continuidade sobre a lacuna.

OCR e modelos ficam na fila ML; a ingestão e o Radar não aguardam inferência.
Limites e passos operacionais estão em [newsletters.md](../newsletters.md).
Nenhuma descoberta de conta/instância AWS é necessária: operação usa workflows
GitHub Actions e o host já configurado no Kamal.
