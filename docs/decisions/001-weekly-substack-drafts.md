# ADR-001: Relatórios semanais persistidos com entrega somente como rascunho

## Status

Aceito — 2026-10-06.

## Contexto

A equipe precisa listar proposições movimentadas na semana anterior e escrever
a análise editorial no Substack. A API oficial não oferece criação de rascunhos;
as bibliotecas disponíveis usam sessões do navegador e endpoints internos.
Rotinas de ingestão atualizam `updated_at` mesmo sem mudança legislativa, e o
refresh existente acompanha apenas proposições com avaliação humana.

## Decisão

Adicionar um app de newsletters independente dos alertas aos assinantes. Usar
datas oficiais de apresentação, eventos, votação e promulgação, e atualizar
históricos de todas as proposições monitoradas em pequenos lotes. Classificar
o estágio editorial da legenda separadamente da velocidade de tramitação.

Congelar snapshot e exportações antes da entrega. Impor unicidade por publicação
e semana, reservar tentativas no banco e salvar o ID remoto antes de verificar
o retorno. Resultados incertos só permitem reconciliação; não há repetição cega
de criação nem atualização de rascunhos editados por pessoas.

Fixar `python-substack==0.9.1` e isolá-lo em um adaptador que permite apenas
leituras e criação de rascunho após autenticação. Desativar explicitamente as
opções de publicação, agendamento, envio e compartilhamento. Usar segredo de
sessão renovável e manter automação desativada até validar um rascunho real.

Permitir disparos manuais por GitHub Actions com datas inclusivas, inclusive até
o dia atual. Reutilizar o host e o acesso SSH do deploy Kamal, sem descoberta de
conta AWS, e compartilhar a trava do deploy para preservar o container durante
a coleta. A mesma data inicial não pode reutilizar silenciosamente um relatório
com outra data final; períodos congelados continuam imutáveis.

## Alternativas

- HTTP direto: exige manter autenticação e documento do editor internamente.
- Automação do navegador: adiciona runtime e dependência da interface visual.
- Exportação manual: preservada como fallback, mas não resolve a criação automática.

## Consequências

A equipe mantém controle editorial e de publicação. Sessões expiradas e mudanças
nos endpoints podem interromper a entrega, mas o conteúdo permanece exportável.
07:00 é um objetivo operacional monitorado, dependente das fontes e da fila.
Classificações desconhecidas e cobertura incompleta ficam explícitas para revisão.
