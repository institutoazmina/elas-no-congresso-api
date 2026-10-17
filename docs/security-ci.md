# Segurança no CI

Os workflows `ci.yml` e `security.yml` validam Pull Requests. O workflow de
deploy chama o mesmo CI para o commit que será implantado e só libera o job
com secrets de produção após sucesso de todos os checks. O deploy aceita
somente `main`, inclusive quando disparado manualmente.

O check obrigatório no ruleset de `main` é `CI passed`, emitido pelo GitHub
Actions. Ele falha se os testes ou qualquer job de segurança falhar ou for
ignorado. As proteções existentes do ruleset foram preservadas.

## Checks

| Check | Critério de falha |
| --- | --- |
| Python dependency audit | Qualquer advisory encontrado pelo pip-audit, ou falha na coleta das dependências |
| Email dependency audit | Vulnerabilidades npm de severidade alta ou crítica, ou falha de consulta |
| Secret scan | Detecção de secrets no histórico Git pelo Gitleaks |
| CodeQL (python/actions) | Falha da análise, resultado com `security-severity >= 7` ou resultado com nível `error` |

O CodeQL usa `security-extended` e publica os resultados na aba Security.
Como a análise por si só não falha quando encontra vulnerabilidades, o script
`scripts/check_codeql_results.py` aplica o limite aos relatórios SARIF. Findings
de menor severidade continuam visíveis para triagem. A configuração usa advanced
setup; não habilite default setup simultaneamente para a mesma análise.

O pip-audit examina o export do `uv.lock` com grupos de desenvolvimento, sem
instalar os pacotes auditados. O sufixo `+cpu` do PyTorch é removido somente da
entrada enviada ao serviço de advisories, para consultar a versão upstream
correspondente; o lockfile e a instalação continuam usando a wheel CPU.
As dependências selecionadas são as do ambiente Linux/Python do CI.

A auditoria npm inclui dependências de build, mesmo que não sejam distribuídas
na imagem final. Ela consulta o lockfile sem executar scripts de instalação.
Os relatórios JSON ficam nos artefatos por 14 dias, inclusive nas falhas.
As auditorias e o CodeQL exigem acesso aos serviços externos; falhas nesses
serviços bloqueiam o check em vez de serem tratadas como resultado limpo.

O Gitleaks CLI tem versão e checksum fixos, roda com `--redact` e não publica
artefatos com secrets. O checkout contém o histórico completo. A varredura no CI
complementa o secret scanning e a push protection habilitados no GitHub.

O workflow Security também roda toda segunda-feira às 08:23 UTC, detectando
novos advisories mesmo sem alterações no código. Todas as actions externas
estão fixadas por SHA. O Renovate mantém as dependências e referências de
actions conforme a [política de atualizações](dependency-updates.md). Versões
embutidas em comandos, como pip-audit e o binário/checksum do Gitleaks, ainda
exigem revisão manual.

## Pendências encontradas em 2026-10-16

A atualização do MJML para `5.4.1` eliminou os 33 findings altos reportados pelo
`npm audit`; os dois templates compilam com a nova versão.

A auditoria Python estrita reportou 68 entradas de advisories em 13 pacotes:
`anyio`, `django`, `idna`, `msgpack`, `pypdf`, `python-engineio`,
`python-socketio`, `setuptools`, `sqlparse`, `torch`, `transformers`, `urllib3`
e `werkzeug`. O total pode incluir aliases/entradas repetidas do mesmo advisory.
Isso não significa que todos os caminhos vulneráveis sejam usados pela API.

**O audit Python e o CI ficarão vermelhos com o lockfile atual, bloqueando merge
e deploy.** Não foram adicionadas exceções. A correção requer atualizar e validar
essas dependências, incluindo sair do Django 5.1 e revisar os pins de PyTorch e
Transformers usados pela QuitérIA. Consulte o JSON do audit para versões
corrigidas e detalhes atualizados; um dos advisories de Transformers foi
reportado sem versão de correção pelo serviço.

## Reprodução local

```bash
uv export --locked --all-groups --no-hashes --no-emit-project --no-header --output-file /tmp/elas-requirements.txt
sed -E 's/^(torch==[^+ ;]+)\+cpu/\1/' /tmp/elas-requirements.txt > /tmp/elas-audit-requirements.txt
uv tool run --from pip-audit==2.10.1 pip-audit -r /tmp/elas-audit-requirements.txt --no-deps --disable-pip --strict
npm audit --prefix apps/subscriptions/emails --package-lock-only --audit-level=high
gitleaks git --redact --no-banner .
```

Para verificar localmente um SARIF produzido pelo CodeQL:

```bash
python scripts/check_codeql_results.py /caminho/dos/relatorios
```

O CodeQL será validado no GitHub após o envio dos workflows. A configuração
local não inicia análises remotas nem publica alterações no repositório.
