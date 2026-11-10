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

## Correções de dependências Python

A auditoria inicial de 2026-10-16 reportou 68 entradas de advisories em 13
pacotes, incluindo aliases/entradas repetidas. As correções seguem commits
individuais, do menor impacto esperado no produto ao maior, com push e
verificação do CI de cada commit antes da próxima atualização.

| Ordem | Pacote | Versão anterior → corrigida | Uso principal |
| --- | --- | --- | --- |
| 1 | msgpack | 1.1.2 → 1.2.1 | Locust, desenvolvimento |
| 2 | python-engineio | 4.13.1 → 4.13.2 | Locust, desenvolvimento |
| 3 | python-socketio | 5.16.1 → 5.16.2 | Locust, desenvolvimento |
| 4 | werkzeug | 3.1.8 → 3.1.9 | Locust/Flask, desenvolvimento |
| 5 | sqlparse | 0.5.5 → 0.6.0 | Parser usado pelo Django |
| 6 | idna | 3.12 → 3.15 | Domínios e validação de e-mail |
| 7 | anyio | 4.13.0 → 4.14.2 | HTTP assíncrono via HTTPX |
| 8 | urllib3 | 2.6.3 → 2.8.0 | Boto3/SES, Requests e outros clientes HTTP |
| 9 | pypdf | 6.13.2 → 6.19.0 | Extração de documentos externos |
| 10 | torch | 2.12.0+cpu → 2.13.0+cpu | Inferência QuitérIA |
| 11 | setuptools | 81.0.0 → 83.0.0 | Dependência do PyTorch |
| 12 | transformers | 5.7.0 → 5.10.4 | Tokenização e inferência QuitérIA |
| 13 | Django | 5.1.15 → 5.2.18 LTS | Framework, autenticação e ORM |

Setuptools foi adiado até a atualização do PyTorch: a wheel CPU 2.12 exigia
`setuptools<82`, incompatível com a correção em 83. A wheel CPU 2.13 remove
esse teto. Transformers 5.10.0 foi retirado pelos mantenedores; o pin usa
5.10.4, uma versão não retirada da mesma série. Os pins de PyTorch e
Transformers continuam explícitos, e o índice CPU permanece obrigatório em
Linux x86_64. O lock universal também atualiza cuda-toolkit e Triton exigidos
pelo PyTorch em outras plataformas; eles não são instalados no Linux x86_64.
Django fica restrito à série LTS 5.2 (`>=5.2.18,<5.3`).

O baseline de inferência anterior às correções não foi regenerado nem teve
suas tolerâncias ampliadas. PDF/OCR, HTTP, autenticação, e-mail e os dois
modelos reais são verificados pelos
[testes de compatibilidade](dependency-compatibility-tests.md). O teste de
senha legada é executado com PBKDF2 real, em vez do MD5 rápido da suíte.

As auditorias permanecem estritas, sem exceções de vulnerabilidades. O relatório
`python-audit.json` de cada execução registra os pacotes ainda afetados naquele
commit. Execuções intermediárias mantêm `CI passed` vermelho enquanto existem
outros pacotes vulneráveis; o resultado final exige também a auditoria limpa.
Os resultados individuais estão no histórico de checks do
[PR #15](https://github.com/institutoazmina/elas-no-congresso-api/pull/15).

A atualização do MJML para `5.4.1` também eliminou os 33 findings altos
reportados inicialmente pelo `npm audit`; os dois templates compilam com ela.

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

As análises CodeQL são executadas no GitHub em cada PR. O comando acima
apenas valida os relatórios SARIF locais; ele não inicia análises remotas.
