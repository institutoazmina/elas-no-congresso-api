# Decisões de arquitetura

ADRs em PT-BR, consolidadas em 08/10/2026 a partir do código e das migrações
versionadas. O status **implementada** descreve o repositório; não comprova
migrações aplicadas, configuração ou execução bem-sucedida em produção.

| ADR | Tema | Estado |
| --- | --- | --- |
| [004](decisions/004-estrutura-do-banco.md) | Estrutura do banco | Implementada |
| [005](decisions/005-sistema-de-alertas.md) | Sistema de alertas | Implementada |
| [001](decisions/001-weekly-substack-drafts.md) | Geração do rascunho do Substack | Implementada; agenda desativada por padrão |
| [002](decisions/002-daily-ingestion-content-versions.md) | Ingestão dos raspadores e análise local de IA | Implementada |

As ADRs 001 e 002 mantêm seus identificadores. A decisão de projeção de leitura
do explorer, antes registrada como ADR-003, foi incorporada à ADR-004; seu número
não será reutilizado. Planos, instruções duplicadas, dumps de SQL/DBML e medições
pontuais foram retirados desta pasta. As regras implementadas relevantes foram
consolidadas nas quatro ADRs.

Cada registro contém contexto, decisão, consequências e referências ao código.
Os diagramas representam relações e fluxos selecionados, não um dump completo
do banco. Models e migrações são a referência para campos e restrições; os testes
referenciados descrevem os contratos verificáveis.
