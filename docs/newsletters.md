# Radar semanal: rascunhos do Substack

O fluxo cria **somente um rascunho**, nunca publica, agenda publicação ou envia
e-mail. A equipe escreve a análise editorial no Substack. A integração está
desativada por padrão até a validação na publicação real.

## Conteúdo

A janela é a segunda-feira anterior às 00:00 até a segunda-feira seguinte às
00:00, exclusiva, em `America/Sao_Paulo`. São incluídas todas as proposições
monitoradas com apresentação, movimento oficial, votação registrada ou
promulgação nessa janela, inclusive as não aprovadas no gerenciador. Alterações
de `updated_at` não são movimentações. Eventos antigos descobertos depois não
entram na semana seguinte.

No uso manual, também é possível informar um período personalizado, com ambas
as datas inclusivas. A data final pode ser hoje: nesse caso o relatório inclui
os dados disponíveis no momento da execução, sem esperar o encerramento do dia.

O rascunho contém LEGENDA, destaques 📃, Radar da Câmara e Radar do Senado.
Cada entrada tem ementa oficial, identificador real, estágio e link oficial.
Não há resumo por IA, autores ou texto editorial. Destaques não são repetidos
nos Radars. As entradas são agrupadas 🔁, 🗳️, 🆕 e revisão, com ordenação por tipo,
número e ano. Tipos como PDL, PEC e PLS são preservados.

O estágio da legenda é independente da celeridade do painel. Códigos conhecidos
da Câmara têm precedência; o Senado e movimentos sem código usam evidências
textuais conservadoras. Um parecer apresentado pode indicar 🗳️, conforme o
exemplo editorial. Aprovação apenas em uma casa não significa proximidade de
sanção. Arquivamento, rejeição e evidências ambíguas ficam com status a revisar.
A classificação utiliza eventos anteriores ao encerramento da semana; o status
atual sem data não é usado para reconstituir uma edição histórica.

## Configuração

Aplicar migrações e configurar a publicação e a sessão no ambiente dos workers:

```sh
uv run python manage.py migrate
```

| Variável | Padrão |
| --- | --- |
| `WEEKLY_NEWSLETTER_ENABLED` | `False` |
| `WEEKLY_NEWSLETTER_BATCH_SIZE` | `5` |
| `SUBSTACK_PUBLICATION_URL` | `https://elasnocongresso.substack.com` |
| `SUBSTACK_COOKIES_STRING` | vazio; segredo obrigatório para entrega |

Entrar na conta autorizada e abrir DevTools → Application → Cookies →
`https://substack.com`. Procurar o cookie de sessão **`substack.sid`** ou
**`connect.sid`**; o nome pode variar entre sessões/versões. Copiar o nome e o
valor exatamente como aparecem, mantendo o nome original. Se ambos estiverem
presentes na requisição autenticada, incluir os dois com seus respectivos valores.

O segredo recebe uma string `nome=valor`, não apenas o valor:

```env
SUBSTACK_COOKIES_STRING=substack.sid=<valor-do-cookie>
# Ou, se esse for o nome encontrado:
SUBSTACK_COOKIES_STRING=connect.sid=<valor-do-cookie>
```

Também é possível copiar o valor inteiro do cabeçalho **Cookie** de uma
requisição autenticada em DevTools → Network → Headers → Request Headers.
Esse é o método recomendado pela [documentação da biblioteca](https://github.com/ma2za/python-substack/blob/main/docs/authentication.md):
a string já contém os pares `nome=valor` separados por ponto e vírgula. Não
incluir o prefixo `Cookie:` nem atributos como `Path`, `Domain` ou `HttpOnly`.
Os nomes de sessão também aparecem na [referência de autenticação](https://github.com/AnthonyDavidAdams/substack-api-reference/blob/main/AUTH.md).

Armazenar em um segredo de implantação, nunca no repositório, em logs ou em
argumentos de comando. O segredo equivale a uma sessão autenticada.
Não há chave da API oficial para criar esses rascunhos. `python-substack==0.9.1`
usa endpoints internos e pode precisar de atualização se eles mudarem.

Em Kamal, fornecer `SUBSTACK_COOKIES_STRING` inclui o segredo nos containers mesmo
com `WEEKLY_NEWSLETTER_ENABLED=False`, permitindo testar a entrega manual sem
ativar a agenda. Com a automação habilitada, o segredo é obrigatório. Com ambos
desativados/ausentes, o deploy continua sem exigir credenciais do Substack.
No deploy via GitHub Actions, definir o secret `SUBSTACK_COOKIES_STRING` e as
repository variables de mesmo nome das três opções não secretas. Reiniciar
workers e Beat quando mudar as opções ou renovar a sessão. Manter as mesmas
configurações da publicação no web, worker e Beat.
Desabilitar a opção também interrompe lotes e entregas automáticas já enfileirados.
Comandos manuais e a ação explícita de entrega do admin continuam disponíveis.

## Validação e uso manual

Visualizar uma semana encerrada sem escrita ou chamadas externas:

```sh
uv run python manage.py weekly_newsletter --week-start 2026-09-28 --dry-run
uv run python manage.py weekly_newsletter --week-start 2026-09-28 --dry-run --format html
```

Preparar, atualizar históricos e criar um rascunho real para validação:

```sh
uv run python manage.py weekly_newsletter --week-start 2026-09-28 --refresh --deliver
```

Para o teste manual, manter `WEEKLY_NEWSLETTER_ENABLED=False`, configurar o segredo
de sessão e fazer redeploy para injetá-lo nos containers. Esse comando pode rodar
com a automação desativada. Confirmar na publicação que
o rascunho está sem agendamento, com as seções e links corretos. Ele nunca
publica ou apaga conteúdo. Sem `--refresh`, a preparação fica marcada como
coleta incompleta; sem `--deliver`, apenas persiste o relatório e suas exportações.
Uma semana já preparada nunca é regenerada silenciosamente.

### Pipeline manual no GitHub Actions

Abrir **Actions → Create Substack draft → Run workflow**, selecionar `main` e
informar `start_date` e `end_date` em `YYYY-MM-DD`. As duas datas são inclusivas,
no fuso de São Paulo, e a data final não pode estar no futuro. Por exemplo:
`2026-09-29` a `2026-10-06` cobre da terça-feira anterior até a terça-feira atual.

`refresh=true` atualiza os históricos oficiais antes de congelar o relatório.
`dry_run=true` apenas mostra o conteúdo disponível, sem coletar, persistir ou
criar rascunho, independentemente de `refresh`. Com `dry_run=false`, o workflow
cria um rascunho e informa o link, a quantidade de proposições e a cobertura da
coleta no resumo da execução. Falhas de autenticação fazem o job falhar, mantendo
o relatório exportável no admin.

O pipeline reutiliza `DEPLOY_HOST` e `SSH_PRIVATE_KEY` do deploy via Kamal;
não consulta perfis, contas ou instâncias AWS. Executa no container web já
implantado, usando a sessão Substack configurada nele. Compartilha a trava de
concorrência do deploy para não trocar o container durante a coleta. Não faz
deploy por conta própria: implantar o suporte às datas antes do primeiro disparo.
Não habilita a agenda semanal.

```sh
gh workflow run newsletter-draft.yml --ref main \
  -f start_date=2026-09-29 -f end_date=2026-10-06 \
  -f refresh=true -f dry_run=false
```

O comando equivalente no servidor é:

```sh
python manage.py weekly_newsletter --start-date 2026-09-29 --end-date 2026-10-06 --refresh --deliver
```

Repetir o mesmo período preserva o snapshot e o rascunho existentes, incluindo
edições humanas. Um início já registrado com outra data final é recusado;
usar `--report-id` para consultar ou entregar aquele período original.

Após a validação, habilitar `WEEKLY_NEWSLETTER_ENABLED=True` no worker e Beat.

## Agenda e cobertura

| Segunda-feira, horário local | Trabalho |
| --- | --- |
| 04:00 | Abrir relatório e atualizar históricos em lotes pequenos |
| 06:00 / 06:10 | Descoberta diária existente da Câmara / Senado |
| 06:35–06:44 | Verificar descoberta e adicionar registros novos à coleta |
| 06:45 | Congelar conteúdo e criar rascunho; falhas anteriores à criação têm até duas novas tentativas |
| 07:00 | Registrar e emitir erro nos logs se a entrega não terminou |

O refresh inclui todas as proposições, não apenas as avaliadas. Matérias do
Senado sem `_senado_process_id` ficam registradas como falha de cobertura;
corrigir esse vínculo pelo pipeline de ingestão antes de confiar em sua timeline.
Votações vêm dos movimentos oficiais e de registros já existentes. Este recurso
não adiciona coleta de votos nominais nem amplia o universo de descoberta.

O worker de produção tem concorrência 1. Medir duração e atraso de fila no
primeiro ciclo: lotes cedem a fila entre execuções, mas não preemptam uma chamada
HTTP em andamento. Se necessário, antecipar a agenda de preparação no código de
settings ou aumentar a capacidade do worker. 07:00 é o objetivo de disponibilidade;
indisponibilidade externa ou fila atrasada pode impedir esse horário.

Se a coleta não terminar, o rascunho mantém os dados disponíveis e uma indicação
visível de cobertura incompleta. No admin, `collection` registra os IDs-alvo,
resultados por proposição e execuções de descoberta; `snapshot` mantém as
evidências de classificação, movimentos, aprovação e categorias humanas.

## Falhas e reconciliação

O admin de **Rascunhos da newsletter** permite inspecionar o relatório, baixar
Markdown/HTML e repetir entrega com permissão de alteração. Exportação exige
permissão de visualização do modelo. Não há endpoint público.
Dar às pessoas revisoras as permissões `view_weeklyreport` e, para repetir entrega,
`change_weeklyreport`.

- **Renovar sessão:** atualizar o segredo e repetir entrega.
- **Falha na entrega:** houve erro antes de tentar criar; é seguro repetir.
- **Reconciliar entrega:** a criação pode ter ocorrido. Repetir procura o título
  semanal original, sem criar outro rascunho. Se o ID já foi salvo, verifica esse ID.
- **Rascunho criado:** novas execuções retornam o registro existente, sem
  sobrescrever edições humanas.
- **Enviando rascunho:** uma tentativa com menos de dez minutos permanece reservada;
  depois disso, repetir entrega reconcilia como resultado incerto, sem nova criação.

```sh
uv run python manage.py weekly_newsletter --report-id 12 --deliver
```

Se alguém mudou o título depois de uma entrega incerta, localizar o rascunho no
Substack e vincular explicitamente seu ID. O comando verifica que ele permanece
rascunho sem agendamento:

```sh
uv run python manage.py weekly_newsletter --report-id 12 --attach-draft-id 12345 --deliver
```

Se não for possível provar o resultado de uma criação, usar a exportação para
transferência manual e manter a entrega incerta. Não excluir o relatório para
forçar uma nova criação. IDs/links são salvos antes da verificação de retorno.
Erros da biblioteca não são copiados para o relatório: podem conter dados de sessão.

## Verificação local

```sh
uv run pytest apps/newsletters/tests
uv run ruff check apps/newsletters config/settings/base.py
uv run python manage.py makemigrations --check --dry-run
```

Os testes usam PostgreSQL para validar restrições, seleção temporal, permissões
e idempotência. Chamadas oficiais e Substack são substituídas nos testes; nenhuma
publicação, envio, agendamento ou criação real é executada por eles.
