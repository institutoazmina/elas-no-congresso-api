# Radar semanal no Substack

Guia operacional do rascunho semanal. As decisões estão na
[ADR-001](decisions/001-weekly-substack-drafts.md).

O fluxo **só cria rascunhos**: nunca publica, agenda ou envia e-mail. O status
`delivered` significa "rascunho criado e verificado".

## Pré-requisitos

1. `SUBSTACK_COOKIES_STRING` com o cabeçalho `Cookie` completo de uma sessão
   autorizada na publicação (segredo de deploy; renove quando expirar).
2. `SUBSTACK_PUBLICATION_URL` como origem HTTPS sem caminho (padrão
   `https://elasnocongresso.substack.com`).
3. Ingestão em dia nas duas casas: a cobertura exige baseline concluída,
   checkpoint cobrindo o período, `covered_until` de até 26 h **agora**, última
   execução diária sem erros e todas as proposições da casa reconciliadas nos
   últimos 8 dias.
4. Para a agenda automática, `WEEKLY_NEWSLETTER_ENABLED=True` no Beat e nos
   workers.

Valide a sessão antes de habilitar:

```bash
python manage.py weekly_newsletter --check-auth
python manage.py weekly_newsletter --dry-run            # semana anterior
```

## Agenda automática (segundas-feiras, São Paulo)

| Horário | Tarefa | Efeito |
| --- | --- | --- |
| 04:00 | `prepare_weekly_report` | Cria o relatório da semana anterior em `collecting` |
| 06:35 | `finish_weekly_collection` | Congela snapshot, Markdown e HTML se a cobertura estiver completa; senão mantém `collecting` |
| 06:45 | `deliver_weekly_report` | Congela (mesmo incompleto, com `is_complete=False`) e entrega se completo; incompleto fica bloqueado. Até 2 retries de 120 s quando `failed` |
| 07:00 | `check_weekly_deadline` | Marca `deadline_missed` se não houver rascunho |

As entradas só são registradas no Beat se a variável estiver ligada ao carregar
as configurações. Como o Beat usa `DatabaseScheduler`, linhas antigas podem
permanecer depois de desligar; as tarefas verificam a variável e não fazem nada.

## Status do `WeeklyReport`

| Status | Significado | Ação |
| --- | --- | --- |
| `collecting` | Criado, ainda não congelado | Aguardar a cobertura ou congelar manualmente |
| `ready` | Congelado, sem tentativa de entrega | Entregar |
| `delivering` | Tentativa reservada (menos de 10 min) | Aguardar; reserva vencida vira incerta |
| `delivered` | Rascunho criado e verificado | Revisar no Substack |
| `auth_required` | Sessão inválida antes de qualquer escrita | Renovar cookie e reenviar |
| `failed` | Falha sem escrita iniciada | Reenviar |
| `uncertain` | Pode existir rascunho no Substack | Procurar manualmente e vincular; não recria às cegas |

`deadline_missed` é um indicador separado: entregue depois de segunda-feira 07:00
ou não entregue até lá. Vale só para a semana padrão (segunda a segunda);
períodos manuais nunca são marcados.

## Comando `weekly_newsletter`

| Opção | Efeito |
| --- | --- |
| `--check-auth` | Verifica a sessão (lista 1 rascunho) e sai |
| `--week-start AAAA-MM-DD` | Segunda-feira de uma semana já encerrada; padrão: semana anterior |
| `--start-date`, `--end-date` | Período manual inclusivo, ambos obrigatórios, fim ≤ hoje |
| `--dry-run` | Imprime sem gravar; calcula a cobertura, inclui o aviso de coleta incompleta e lista os motivos no stderr |
| `--format markdown\|html` | Formato do `--dry-run` (padrão `markdown`) |
| `--deliver` | Cria ou reconcilia o rascunho; falha se o resultado não for `delivered` |
| `--allow-incomplete` | Permite `--deliver` com cobertura incompleta (aviso no texto) |
| `--report-id N` | Atua sobre relatório existente, sem regenerar |
| `--attach-draft-id N` | Com `--report-id` e status `uncertain`: verifica o rascunho e vincula |
| `--refresh` | Recuperação: atualiza o histórico de todas as proposições antes de congelar; em relatório já congelado só emite aviso |

Combinações recusadas: `--dry-run` com `--refresh`, `--deliver`, `--report-id`
ou `--attach-draft-id`; `--report-id` com `--week-start` ou `--refresh`; datas
manuais com `--week-start` ou `--report-id`.

### Receitas

```bash
# Gerar e entregar a semana de 28/09/2026
python manage.py weekly_newsletter --week-start 2026-09-28 --deliver

# Reentregar um relatório já congelado
python manage.py weekly_newsletter --report-id 12 --deliver

# Resolver um relatório incerto após localizar o rascunho no Substack
python manage.py weekly_newsletter --report-id 12 --attach-draft-id 12345 --deliver

# Entregar mesmo com cobertura incompleta (exceção editorial)
python manage.py weekly_newsletter --report-id 12 --deliver --allow-incomplete
```

Com `--refresh`, `is_complete` passa a significar "todos os refresh
retornaram `ok`", e não a cobertura de `source_coverage`. Em relatório já
congelado, `--refresh` não recoleta nada e emite um aviso; o comando continua
idempotente.

## Workflow `newsletter-draft.yml`

Manual, só em `main`, com timeout de 360 min e o mesmo grupo de concorrência do
deploy. Entradas: `start_date`, `end_date` (validadas em São Paulo) e `dry_run`.
Sem `dry_run`, executa `--check-auth` e depois o comando com `--deliver`. A saída
vai para o resumo do job. O cookie do Substack vem do ambiente do container, não
dos segredos do workflow.

## Admin

**Newsletters → Relatórios semanais** é somente leitura, sem inclusão nem
exclusão:

- filtros por status, `is_complete` e `deadline_missed`;
- exportação Markdown/HTML em `<id>/export/<formato>/` (permissão de visualização);
- link para o rascunho no Substack;
- ação **Repetir/reconciliar entrega sem alterar rascunhos** (`retry_delivery`, permissão de alteração) para `failed`,
  `auth_required`, `uncertain` e `delivering`. A ação respeita o bloqueio de
  cobertura incompleta.

Se a integração falhar, exporte o Markdown ou HTML e crie o rascunho manualmente.

## Conteúdo

Título `Elas no Congresso — Radar dd/mm/aaaa a dd/mm/aaaa`. O texto reúne a
LEGENDA, destaques e um Radar por casa, com ementa, identificação, estágio,
autoria (partido/UF) e link oficial. Apenas links de `camara.leg.br` e
`senado.leg.br` são mantidos; outros viram "(link oficial a revisar)". Seção
vazia mostra "Nenhuma movimentação registrada nesta seção." A análise editorial
é escrita pela equipe no Substack.
