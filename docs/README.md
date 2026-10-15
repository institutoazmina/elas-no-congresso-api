# Documentação

Documentação técnica da API Elas no Congresso, em PT-BR. Revisada em 08/10/2026
contra o código da branch `main`. Descreve o repositório; não comprova
migrações aplicadas, configuração ou execução bem-sucedida em produção.

## Guias

| Documento | Conteúdo |
| --- | --- |
| [Visão geral](visao-geral.md) | Componentes, apps, ciclo diário, regras de domínio (avaliação, celeridade, categorias) |
| [Desenvolvimento local](desenvolvimento.md) | Setup com Docker/uv, dados de desenvolvimento, testes, lint, scripts |
| [Configuração](configuracao.md) | Todas as variáveis de ambiente e diferenças entre dev, prod e test |
| [API HTTP](api.md) | Endpoints, filtros, paginação, cache e health checks |
| [Banco de dados](banco-de-dados.md) | Inventário de models, restrições e extensões |
| [Ingestão e QuitérIA](ingestao.md) | Pipeline, comandos `ingestion_sync` e `classification_backfill`, enriquecimento de parlamentares |
| [Alertas por e-mail](alertas.md) | Inscrição, critérios (AST), correspondência, resumo diário |
| [Radar semanal no Substack](newsletter.md) | Agenda, status, comando `weekly_newsletter`, recuperação |
| [Admin](admin.md) | Curadoria, CMS do site e ações administrativas |
| [Deploy e operação](operacao.md) | Imagem Docker, Kamal, workflows, agenda do Beat, checklist de incidentes |

Templates de e-mail: [`apps/subscriptions/emails/README.md`](../apps/subscriptions/emails/README.md).

## Decisões de arquitetura

ADRs consolidadas em 08/10/2026 a partir do código e das migrações versionadas.

| ADR | Tema | Estado |
| --- | --- | --- |
| [004](decisions/004-estrutura-do-banco.md) | Estrutura do banco | Implementada |
| [005](decisions/005-sistema-de-alertas.md) | Sistema de alertas | Implementada |
| [006](decisions/006-cms-do-site.md) | CMS do site no admin | Implementada para alertas |
| [001](decisions/001-weekly-substack-drafts.md) | Geração do rascunho do Substack | Implementada; agenda desativada por padrão |
| [002](decisions/002-daily-ingestion-content-versions.md) | Ingestão dos raspadores e análise local de IA | Implementada |

As ADRs 001 e 002 mantêm seus identificadores. A decisão de projeção de leitura
do explorer, antes registrada como ADR-003, foi incorporada à ADR-004; seu número
não será reutilizado.

Cada ADR registra contexto, decisão, consequências e referências ao código; os
guias acima descrevem uso e operação. Quando houver conflito, models, migrações
e testes são a referência.
